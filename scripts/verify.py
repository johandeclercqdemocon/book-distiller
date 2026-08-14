#!/usr/bin/env python3
"""Deterministic checks on a finished summary, before a model ever reviews it.

    uv run python scripts/verify.py <slug> [--lenient] [--max 40]

Code does bookkeeping so the adversary reviewer can spend its attention on judgment.
Everything here is mechanical: does the citation resolve, does the number exist in the
text it claims to come from, is every chapter represented, is the quote real.

Severities and check codes are specified in spec/summary-format.md §7. Exit status is 1
when anything Critical or Major survives, so this can gate a pipeline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

CRITICAL, MAJOR, MINOR = "critical", "major", "minor"
ORDER = {CRITICAL: 0, MAJOR: 1, MINOR: 2}

# Prose share of in-scope source words. Copied material — tables, verbatim blocks, the
# identifier ledger — is excluded by prose_words(), so this governs compression of the
# explanation only.
#
# The 8-12% band comes from the Marco summary: 6,117 words from 64,534, a conceptual book
# where the summary's job is mostly to compress argument. A protocol reference is a different
# shape. sip-johnston needs prose to state polarity rules precisely, adjudicate seventeen
# book self-contradictions, and say what it does not cover — and landed at 22.3% after a
# restoration round that added no prose padding, only tables.
#
# PROVISIONAL: this band is drawn from ONE technical book. It is deliberately wide so it acts
# as a sanity check rather than a target, and every run records its own share in verify.json
# — revisit once three or four technical books have been through, and let the data set it.
#
# Raised 15-25% -> 15-30% on 2026-08-14, by the reader's decision. The 25% ceiling was set
# before ch16's seven wire-format listings and the eight restored reference tables went in, and
# it had 0.1pp of headroom left: any table restored afterwards needed a locator line and a
# stated declaration, and those are prose. A ceiling that makes the project's own rules — cite
# every claim, declare every omission — cost budget is a ceiling working against the summary.
DEEP_BUDGET = (0.08, 0.12)
TECHNICAL_BUDGET = (0.15, 0.30)
BRIEF_BUDGET = (1200, 1800)  # absolute words
UNDERWEIGHT_RATIO = 0.25  # citation share vs word share

# A locator entry: label, optionally p.N or pp.N-M. Comma before the page is tolerated.
_ENTRY_RE = re.compile(
    r"^\s*(?P<label>[A-Za-z]+[\s.\-_]*\d+)\s*,?\s*"
    r"(?:pp?\.\s*(?P<start>\d+)(?:\s*[-–]\s*(?P<end>\d+))?)?\s*$"
)
_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
_CODE_RE = re.compile(r"`([^`\n]{1,60})`")
_QUOTE_RE = re.compile(r'["“]([^"”\n]{12,300})["”]')
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^(```|~~~)(.*)$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SYNTHESIS_RE = re.compile(r"not the book'?s|\[synthesis\]", re.I)


@dataclass
class Finding:
    code: str
    severity: str
    line: int
    message: str
    evidence: str = ""
    where: str = "deep"

    def __str__(self) -> str:
        ev = f"\n      {self.evidence}" if self.evidence else ""
        return f"  {self.where}:{self.line:<5} {self.code:<28} {self.message}{ev}"


@dataclass
class Locator:
    label: str
    raw: str
    start: int | None = None
    end: int | None = None
    canonical: bool = True


@dataclass
class Block:
    text: str
    line: int
    kind: str  # para | fence | heading
    fence_info: str = ""
    locators: list[Locator] = field(default_factory=list)
    inherited: list[Locator] = field(default_factory=list)
    front_matter: bool = False
    synthesis: bool = False
    heading_path: tuple[str, ...] = ()

    @property
    def effective(self) -> list[Locator]:
        return self.locators or self.inherited


def parse_locators(text: str) -> list[Locator]:
    """Pull locators out of `[...]` spans, ignoring markdown links and other brackets."""
    out: list[Locator] = []
    for m in _BRACKET_RE.finditer(text):
        tail = text[m.end() : m.end() + 1]
        if tail in ("(", "["):  # a markdown link or reference, not a citation
            continue
        for entry in m.group(1).split(";"):
            em = _ENTRY_RE.match(entry)
            if not em:
                continue
            raw = em.group("label")
            label = corpus.normalise_label(raw)
            start = int(em.group("start")) if em.group("start") else None
            end = int(em.group("end")) if em.group("end") else start
            canonical = raw == label and "," not in entry
            out.append(Locator(label=label, raw=raw.strip(), start=start, end=end, canonical=canonical))
    return out


def parse_blocks(md: str) -> list[Block]:
    lines = md.splitlines()
    blocks: list[Block] = []
    stack: list[tuple[int, str, list[Locator]]] = []  # (level, title, locators)
    buf: list[str] = []
    buf_start = 0
    front_matter = True
    in_fence = False
    fence_marker = ""
    fence_info = ""

    def inherited() -> list[Locator]:
        for _lvl, _t, locs in reversed(stack):
            if locs:
                return locs
        return []

    def flush(kind: str = "para", info: str = "") -> None:
        nonlocal buf, buf_start
        if buf:
            text = "\n".join(buf)
            if text.strip():
                blocks.append(
                    Block(
                        text=text,
                        line=buf_start,
                        kind=kind,
                        fence_info=info,
                        locators=parse_locators(text) if kind != "fence" else parse_locators(info),
                        inherited=inherited(),
                        front_matter=front_matter,
                        synthesis=bool(_SYNTHESIS_RE.search(text))
                        or any(_SYNTHESIS_RE.search(t) for _l, t, _x in stack),
                        heading_path=tuple(t for _l, t, _x in stack),
                    )
                )
        buf, buf_start = [], 0

    for i, raw in enumerate(lines, start=1):
        if fm := _FENCE_RE.match(raw):
            if not in_fence:
                flush()
                in_fence, fence_marker, fence_info = True, fm.group(1), fm.group(2)
                buf, buf_start = [], i
                continue
            if raw.startswith(fence_marker):
                flush("fence", fence_info)
                in_fence, fence_marker, fence_info = False, "", ""
                continue
        if in_fence:
            if not buf_start:
                buf_start = i
            buf.append(raw)
            continue

        if hm := _HEADING_RE.match(raw):
            flush()
            level, title = len(hm.group(1)), hm.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title, parse_locators(title)))
            blocks.append(
                Block(
                    text=raw,
                    line=i,
                    kind="heading",
                    locators=parse_locators(title),
                    front_matter=front_matter,
                    heading_path=tuple(t for _l, t, _x in stack),
                )
            )
            continue

        if raw.strip() in ("---", "***", "___"):
            flush()
            front_matter = False
            continue

        if not raw.strip():
            flush()
            continue

        if not buf:
            buf_start = i
        buf.append(raw)

    flush()
    return blocks


def _despace(text: str) -> str:
    return re.sub(r"\s+", "", text)


def strip_markup(text: str) -> str:
    text = _BRACKET_RE.sub(" ", text)
    text = _CODE_RE.sub(" ", text)
    text = re.sub(r"https?://\S+", " ", text)
    return "\n".join(_LIST_RE.sub("", ln.lstrip("#").strip()) for ln in text.splitlines())


class Verifier:
    def __init__(self, book: corpus.Book, where: str, md: str):
        self.book, self.where, self.md = book, where, md
        self.blocks = parse_blocks(md)
        self.findings: list[Finding] = []
        self.citations: dict[str, int] = {p.label: 0 for p in book.parts}

    def add(self, code, sev, line, msg, evidence="") -> None:
        self.findings.append(Finding(code, sev, line, msg, evidence[:200], self.where))

    def parts_for(self, locs: list[Locator]) -> list[corpus.Part]:
        return [p for p in (self.book.by_label.get(l.label) for l in locs) if p is not None]

    def run(self) -> list[Finding]:
        for b in self.blocks:
            self.check_locators(b)
        self.check_citation_requirement()
        self.check_content()
        self.check_coverage()
        self.check_structure()
        self.findings.sort(key=lambda f: (ORDER[f.severity], f.line))
        return self.findings

    # --- checks ---------------------------------------------------------
    def check_locators(self, b: Block) -> None:
        for loc in b.locators:
            part = self.book.by_label.get(loc.label)
            if part is None:
                self.add(
                    "locator.unknown_label",
                    CRITICAL,
                    b.line,
                    f"citation [{loc.raw}] does not match any part in meta.json",
                    f"known labels: {', '.join(sorted(self.book.by_label))}",
                )
                continue
            self.citations[loc.label] += 1
            if loc.start is not None:
                for page in filter(None, (loc.start, loc.end)):
                    inside = part.covers_page(page)
                    if inside is False:
                        self.add(
                            "locator.page_out_of_range",
                            MAJOR,
                            b.line,
                            f"[{loc.raw} p.{page}] is outside {loc.label}'s printed range "
                            f"{part.printed_start}-{part.printed_end}",
                        )
            if not loc.canonical:
                self.add(
                    "locator.style",
                    MINOR,
                    b.line,
                    f"non-canonical citation [{loc.raw}] — write [{loc.label}]",
                )

    def check_citation_requirement(self) -> None:
        for b in self.blocks:
            if b.kind == "heading" or b.front_matter or b.synthesis:
                continue
            if "<!-- nocite -->" in b.text or b.effective:
                continue
            self.add(
                "locator.missing",
                MINOR,
                b.line,
                "claim block has no locator",
                b.text.strip().splitlines()[0],
            )

    def check_content(self) -> None:
        for b in self.blocks:
            # A transcribed figure was read off a rendered page image. Its numbers, addresses
            # and identifiers exist only in the diagram, never in the extracted text, so the
            # numeral and identifier checks are guaranteed to fire on every one of them.
            # Quotes and verbatim blocks are still checked: those must come from the text.
            transcribed = "TRANSCRIBED" in b.text.upper() or any(
                "TRANSCRIBED" in h.upper() for h in b.heading_path
            )
            parts = self.parts_for(b.effective)
            if b.front_matter:
                continue
            if b.kind == "fence" and b.locators:
                self.check_verbatim(b, parts)
            if not parts:
                continue
            self.check_quotes(b, parts)
            if transcribed:
                continue
            self.check_identifiers(b, parts)
            if b.kind != "fence":
                self.check_numbers(b, parts)

    def check_verbatim(self, b: Block, parts: list[corpus.Part]) -> None:
        needle = corpus.flatten(b.text, strip_markup=True).strip()
        if not needle or any(needle in p.flat for p in parts):
            return
        # A long block may span a page break the extractor handled differently; try the head.
        head = " ".join(needle.split()[:12])
        sev = MAJOR if any(head in p.flat for p in parts) else CRITICAL
        self.add(
            "verbatim.mismatch",
            sev,
            b.line,
            "block marked verbatim does not match the cited source text"
            + (" beyond its first line" if sev == MAJOR else ""),
            needle[:120],
        )

    def check_quotes(self, b: Block, parts: list[corpus.Part]) -> None:
        for m in _QUOTE_RE.finditer(b.text):
            quote = m.group(1)
            if len(quote.split()) < 5:
                continue
            needle = corpus.flatten(quote, strip_markup=True).lower()
            if not any(needle in p.flat_lower for p in parts):
                self.add("quote.not_found", CRITICAL, b.line, "quoted text is not in the cited part", quote)

    def check_identifiers(self, b: Block, parts: list[corpus.Part]) -> None:
        for m in _CODE_RE.finditer(b.text):
            tok = m.group(1).strip()
            if not tok or not re.search(r"[A-Za-z0-9]", tok) or len(tok.split()) > 6:
                continue
            needle = corpus.flatten(tok, strip_markup=True)
            if any(needle in p.flat for p in parts):
                continue
            # Second chance with all whitespace removed. pdftotext splits ligatures, so this
            # book's `a=fingerprint` and `a=confid` extract as `a=fi ngerprint` and `a=confi d`
            # and a correct transcription looks invented. Confirmed against the rendered page:
            # both are single words in print. Scoped to identifiers, which are structured
            # tokens — doing the same for prose quotes would let "at one" match "atone".
            if any(_despace(needle) in _despace(p.flat) for p in parts):
                continue
            if any(needle.lower() in p.flat_lower for p in parts):
                self.add("identifier.case", MINOR, b.line, f"`{tok}` appears in source with different case")
                continue
            self.add("identifier.not_found", MAJOR, b.line, f"`{tok}` does not appear in the cited part")

    def check_numbers(self, b: Block, parts: list[corpus.Part]) -> None:
        for tok in _NUM_RE.findall(strip_markup(b.text)):
            norm = tok.replace(",", "")
            if any(norm in p.numbers or tok in p.numbers for p in parts):
                continue
            digits = norm.replace(".", "")
            if len(digits) <= 1:
                continue  # single digits are noise: "three ways", list residue
            self.add(
                "numeral.not_found",
                MAJOR,
                b.line,
                f"the figure {tok} does not appear in the cited part",
                b.text.strip().splitlines()[0],
            )

    def check_coverage(self) -> None:
        total = sum(self.citations.values()) or 1
        for p in self.book.in_scope:
            n = self.citations[p.label]
            if n == 0:
                self.add(
                    "coverage.part_uncited",
                    MAJOR,
                    0,
                    f"{p.label} ({p.title[:60]}) is never cited — {p.words:,} words unrepresented",
                )
            elif self.book.source_words and (
                n / total < UNDERWEIGHT_RATIO * (p.words / self.book.source_words)
            ):
                self.add(
                    "coverage.underweight",
                    MINOR,
                    0,
                    f"{p.label} has {n/total:.1%} of citations for {p.words/self.book.source_words:.1%} of the text",
                )

    def check_structure(self) -> None:
        if self.where != "deep":
            return
        headings = [b.text for b in self.blocks if b.kind == "heading"]
        joined = "\n".join(headings).lower()
        for needle, label in (
            ("does not cover", "a 'what the book does not cover' section"),
            ("index", "a chapter -> topic index"),
        ):
            if needle not in joined:
                self.add("structure.missing_section", MAJOR, 0, f"missing {label}")
        idx = self.index_section()
        if idx is not None:
            for p in self.book.parts:
                if not self.indexed(p, idx):
                    self.add(
                        "structure.part_not_indexed",
                        MAJOR,
                        0,
                        f"{p.label} is absent from the chapter index",
                    )

    @staticmethod
    def indexed(part: corpus.Part, idx: str) -> bool:
        """The index may name a part as `ch07`, `ch.7`, or a bare `| 7 |` table cell."""
        if m := re.match(r"([a-z]+?)0*(\d+)$", part.label):
            stem, num = m.group(1), m.group(2)
            for pattern in (
                rf"{stem}\.?\s*0*{num}\b",  # ch07, ch.7, ch 7
                rf"^\|\s*0*{num}\s*\|",  # a table row keyed by chapter number
            ):
                if re.search(pattern, idx, re.M):
                    return True
        title = (part.title or "").lower().strip()
        return bool(title) and title[:24] in idx

    def index_section(self) -> str | None:
        take, out = False, []
        for b in self.blocks:
            if b.kind == "heading":
                take = "index" in b.text.lower()
                continue
            if take:
                out.append(b.text.lower())
        return "\n".join(out) if out else None


_HEADER_COUNT_RE = re.compile(r"(\d+)\s+of\s+(\d+)\s+(?:expected\s+)?(figures?|parts?|chapters?|digests?)", re.I)


def check_header_counts(book: corpus.Book, deep: str, root: Path) -> list[Finding]:
    """Cross-check any 'N of M' claim in the review header against the artifacts on disk.

    Front matter is exempt from the locator rules, which left the most trust-bearing block in
    the document as the least-checked one — and an assembled summary duly claimed "43 of 43
    expected figures transcribed, zero gaps" when 17 were rendered and 56 transcribed. A
    fabricated provenance statistic should cost a script, not a reviewer.
    """
    out: list[Finding] = []
    header = deep.split("\n---\n", 1)[0]
    work = book.work_dir(root)

    truth: dict[str, int] = {}
    if (f := work / "figures.json").is_file():
        truth["figure"] = len(json.loads(f.read_text()).get("figures", []))
    truth["part"] = truth["chapter"] = len(book.in_scope)
    truth["digest"] = len(book.digest_paths(root))

    for line_no, line in enumerate(header.splitlines(), start=1):
        for m in _HEADER_COUNT_RE.finditer(line):
            claimed, total, kind = int(m.group(1)), int(m.group(2)), m.group(3).rstrip("s").lower()
            actual = truth.get(kind)
            if actual is None:
                continue
            if total != actual or claimed > actual:
                out.append(
                    Finding(
                        "header.count_unsupported",
                        CRITICAL,
                        line_no,
                        f"header claims {claimed} of {total} {kind}s; the artifacts say {actual}",
                        m.group(0),
                    )
                )
    return out


# What a part's `reproduce` directive demands, and how to tell whether the summary honoured it.
# Each entry: (what to look for in the summary, what the digest records it under).
_REPRODUCE_KINDS = {
    "figures": ("figure transcriptions", "figures"),
    "verbatim": ("verbatim wire-format blocks", "verbatim"),
    "tables": ("reproduced tables", "tables"),
}


def check_reproduce(book: corpus.Book, deep: str, root: Path) -> list[Finding]:
    """Enforce `"reproduce": [...]` in a part's meta.json entry.

    A `scope` note is prose, and assembly may reasonably reinterpret it. Three times on this
    project a part whose scope said its figures *were* the chapter had them compressed out —
    legally, with a declaration, because a declared omission satisfies every other rule. A
    declaration says the omission was honest; it cannot say it was wanted.

    So `reproduce` is the directive that outranks assembly's judgement, and it is checked here
    rather than asked for in a prompt. If a part demands its figures and the summary carries
    none of that part's figure transcriptions, that is Critical — not because the summary lied,
    but because the reader asked for something and did not get it.
    """
    out: list[Finding] = []
    for part in book.meta.get("parts", []):
        label = corpus.normalise_label(part["label"])
        for kind in part.get("reproduce", []):
            if kind not in _REPRODUCE_KINDS:
                out.append(Finding("reproduce.unknown_kind", MINOR, 0,
                                   f"{label}: unknown reproduce directive {kind!r}; known: "
                                   f"{', '.join(sorted(_REPRODUCE_KINDS))}"))
                continue
            human, section = _REPRODUCE_KINDS[kind]
            digest = root / "work" / book.slug / "digests" / f"{label}.md"
            if not digest.is_file():
                continue
            want = _digest_section_size(digest.read_text(), section)
            got = _summary_carries(deep, label, kind)
            if want and not got:
                out.append(Finding(
                    "reproduce.directive_unmet", CRITICAL, 0,
                    f"{label} requires `reproduce: {kind}` and the summary carries no {human} "
                    f"from it; the digest holds {want} lines of them",
                    f"meta.json scope: {str(part.get('scope',''))[:120]}"))
    return out


def _digest_section_size(md: str, section: str) -> int:
    take, n = False, 0
    for line in md.splitlines():
        if line.startswith("## "):
            take = section in line.lower()
            continue
        if take and line.strip():
            n += 1
    return n


def _summary_carries(deep: str, label: str, kind: str) -> bool:
    """Does the summary hold material of this kind attributed to this part?"""
    marker = {"figures": "TRANSCRIBED", "verbatim": "```", "tables": "|"}[kind]
    for block in parse_blocks(deep):
        locs = [l.label for l in (block.locators or block.inherited)]
        if label not in locs:
            continue
        if kind == "verbatim" and block.kind == "fence":
            # `parse_blocks` strips a fence's own delimiters, so the ``` marker never
            # survives into `block.text` and a correctly marked verbatim block could not
            # satisfy this check by string match. The block's kind is the marker.
            return True
        hay = block.text + " " + " ".join(block.heading_path)
        if marker in hay or (kind == "figures" and "TRANSCRIBED" in hay.upper()):
            return True
    return False


def words_of(md: str) -> int:
    return len(md.split())


def prose_words(md: str) -> int:
    """Words outside fenced blocks and tables.

    The length budget governs compression, and a reproduced wire format or a merged
    identifier ledger is a copy, not compression — there is no such thing as copying 10% of
    a header-field table. Counting them would penalise exactly the retention the format
    exists to guarantee.
    """
    out, in_fence = 0, False
    for line in md.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith("|"):
            continue
        out += len(line.split())
    return out


def check_lengths(book: corpus.Book, deep: str | None, brief: str | None) -> list[Finding]:
    out = []
    if deep is not None and book.source_words:
        prose = prose_words(deep)
        share = prose / book.source_words
        budget = TECHNICAL_BUDGET if book.technical else DEEP_BUDGET
        kind = "technical" if book.technical else "general"
        if not budget[0] <= share <= budget[1]:
            out.append(
                Finding(
                    "length.out_of_budget",
                    MINOR,
                    0,
                    f"deep summary prose is {share:.1%} of in-scope source ({prose:,} prose "
                    f"words of {book.source_words:,}; {words_of(deep):,} total incl. tables and "
                    f"verbatim); {kind} budget is {budget[0]:.0%}-{budget[1]:.0%}",
                    where="deep",
                )
            )
    if brief is not None:
        n = prose_words(brief)
        if not BRIEF_BUDGET[0] <= n <= BRIEF_BUDGET[1]:
            out.append(
                Finding(
                    "length.out_of_budget",
                    MINOR,
                    0,
                    f"brief is {n:,} words; budget is {BRIEF_BUDGET[0]:,}-{BRIEF_BUDGET[1]:,}",
                    where="brief",
                )
            )
    return out


def check_staleness(book: corpus.Book) -> list[Finding]:
    digests = book.digest_paths(ROOT)
    if not digests or not book.deep_path.is_file():
        return []
    newest = max(d.stat().st_mtime for d in digests)
    if newest > book.deep_path.stat().st_mtime:
        return [
            Finding(
                "staleness.digest_newer",
                MAJOR,
                0,
                "a digest is newer than the summary — the summary was built from stale input",
            )
        ]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--summary", type=Path, help="override the deep summary path")
    ap.add_argument("--brief", type=Path, help="override the brief path")
    ap.add_argument("--json", type=Path, help="where to write the machine-readable report")
    ap.add_argument("--max", type=int, default=25, help="findings printed per severity (0 = all)")
    ap.add_argument("--lenient", action="store_true", help="always exit 0")
    args = ap.parse_args()

    book = corpus.load(args.slug)
    missing_text = [p.label for p in book.parts if not p.exists]
    findings: list[Finding] = []

    deep_path = args.summary or book.deep_path
    brief_path = args.brief or book.brief_path
    deep = deep_path.read_text() if deep_path.is_file() else None
    brief = brief_path.read_text() if brief_path.is_file() else None

    if deep is None:
        print(f"no deep summary at {deep_path}", file=sys.stderr)
        return 2
    findings += Verifier(book, "deep", deep).run()
    if brief is not None:
        findings += Verifier(book, "brief", brief).run()
    else:
        findings.append(Finding("artifact.brief_missing", MAJOR, 0, f"no brief at {brief_path}"))
    findings += check_lengths(book, deep, brief)
    findings += check_staleness(book)
    findings += check_header_counts(book, deep, ROOT)
    findings += check_reproduce(book, deep, ROOT)
    findings.sort(key=lambda f: (ORDER[f.severity], f.where, f.line))

    counts = {s: sum(1 for f in findings if f.severity == s) for s in (CRITICAL, MAJOR, MINOR)}
    print(f"\n{book.title}  [{book.slug}]")
    print(
        f"{len(book.parts)} parts · {book.source_words:,} source words · "
        f"deep {words_of(deep):,} words"
        + (f" · brief {words_of(brief):,}" if brief else "")
    )
    if missing_text:
        print(f"! no extracted text for: {', '.join(missing_text)} — checks against those parts are blind")
    for sev in (CRITICAL, MAJOR, MINOR):
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        print(f"\n{sev.upper()}  ({len(group)})")
        shown = group if args.max == 0 else group[: args.max]
        for f in shown:
            print(f)
        if len(group) > len(shown):
            print(f"  … {len(group) - len(shown)} more (use --max 0)")

    print(
        f"\ncritical {counts[CRITICAL]} · major {counts[MAJOR]} · minor {counts[MINOR]}"
        f"  ->  {'BLOCKED' if counts[CRITICAL] or counts[MAJOR] else 'clean enough for review'}"
    )

    out = args.json or book.work_dir(ROOT) / "verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "slug": book.slug,
                "source_words": book.source_words,
                "counts": counts,
                "missing_text": missing_text,
                "findings": [asdict(f) for f in findings],
            },
            indent=2,
        )
    )
    print(f"wrote {out}")

    return 0 if args.lenient or not (counts[CRITICAL] or counts[MAJOR]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
