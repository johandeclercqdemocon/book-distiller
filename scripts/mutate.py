#!/usr/bin/env python3
"""Inject known defects into a summary, so a reviewer can be measured instead of trusted.

    uv run python scripts/mutate.py <slug> [--n 12] [--seed 7] [--classes number,polarity]

A reviewer that finds nothing is indistinguishable from a summary with nothing wrong. The
only way to tell them apart is to hand it a summary you have broken on purpose and count what
comes back. This writes a mutated copy plus an answer key; `score.py` compares a review
against that key.

The defect classes are the ones that actually happened. `polarity` reverses a rule — the
`memory/` placement claim in the Marco summary was stated backwards and read perfectly well.
`citation` points a claim at a chapter that does not discuss it. `number` alters a figure by a
plausible amount. `fabrication` promotes a fenced synthesis note into an unmarked claim.
`deletion` removes a table row, which is the one class a reader cannot notice by reading.

Nothing is written to the corpus: mutants live in work/<slug>/mutants/.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

POLARITY = [
    (r"\bnever\b", "always"), (r"\balways\b", "never"),
    (r"\bmust not\b", "must"), (r"\bhop-by-hop\b", "end-to-end"),
    (r"\bend-to-end\b", "hop-by-hop"), (r"\badds a\b", "removes a"),
    (r"\bremoves a\b", "adds a"), (r"\brequest\b", "response"),
    (r"\bcase-insensitive\b", "case-sensitive"), (r"\bsignificant\b", "insignificant"),
    (r"\bis required\b", "is optional"), (r"\bis optional\b", "is required"),
]
_LOCATOR_RE = re.compile(r"\[(ch\d{2})\s+(pp?\.\s*\d+(?:-\d+)?)\]")
# One definition, used to both *select* a fabrication candidate and *strip* it. They were
# separate — the selector matched any line containing "not the book's", which also catches
# prose in the unresolved-questions section, and the stripper then no-opped on those lines.
# The key recorded a defect the mutant did not contain, and the reviewer was scored as
# having missed something that was never there.
_SYNTH_MARKER_RE = re.compile(r"\*\*My construction, not the book'?s\.?\*\*\s*", re.I)
_NUM_RE = re.compile(r"(?<![\w.])(\d{2,4})(?![\w.])")
_TABLE_ROW_RE = re.compile(r"^\|(?!\s*[-: ]+\|).*\|\s*$")


@dataclass
class Defect:
    id: int
    kind: str
    line: int
    before: str
    after: str
    hint: str


def _lines_with(md: list[str], pred) -> list[int]:
    return [i for i, ln in enumerate(md) if pred(ln)]


def load_claims(slug: str) -> list[str]:
    """Read the per-book bank of synthesis claims for the `synthesis` class.

    The claims are handwritten, not generated: producing a sentence the book does not say,
    about a book, is judgment, and judgment does not belong in this file. What belongs here
    is the bookkeeping — pick one, append it, record where.

    **The bank must declare itself verified.** A claim the book actually makes is not a
    defect: flagging it would be a false positive, and scoring a reviewer for missing it
    repeats exactly the bug this class was written to replace. The `# verified:` line is the
    human's assertion that every claim has been checked against the source and is absent
    from it.
    """
    path = ROOT / "evals" / "synthesis" / f"{slug}.txt"
    if not path.is_file():
        raise SystemExit(f"no synthesis bank at {path} — write one, or drop `synthesis` from --classes")
    lines = path.read_text().splitlines()
    if not any(re.match(r"#\s*verified:\s*\S", ln) for ln in lines):
        raise SystemExit(
            f"{path}: bank is unverified. Check every claim against the source — a claim the "
            f"book does make is not a defect — then set the `# verified:` line to the date."
        )
    claims = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not claims:
        raise SystemExit(f"{path}: no claims")
    return claims


def _prose_targets(md: list[str], body: int) -> list[int]:
    """Cited prose paragraphs an unmarked claim could be appended to and read as the book's.

    Excludes tables, headings, blockquotes and anything inside a fence — the verbatim classes
    are fenced, and a sentence of prose appended inside a wire-format block is not a defect a
    reader could miss, it is obvious damage. Requires an existing locator so the fabricated
    claim inherits the authority of the cited material around it, and requires the line to end
    like a sentence so the append reads as the next one.
    """
    out, fenced = [], False
    for i, ln in enumerate(md):
        if ln.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or i < body:
            continue
        s = ln.strip()
        if not s or s.startswith(("#", "|", ">")) or _TABLE_ROW_RE.match(ln):
            continue
        if _SYNTH_MARKER_RE.search(ln):  # already fenced as synthesis; appending contradicts it
            continue
        if _LOCATOR_RE.search(ln) and s.endswith((".", ".**", ".*", ".`")):
            out.append(i)
    return out


def mutate(md: list[str], kinds: list[str], n: int, rng: random.Random, labels: list[str],
           only: str | None = None, claims: list[str] | None = None) -> list[Defect]:
    """Apply n defects in place; return the answer key."""
    defects: list[Defect] = []
    unused_claims = list(claims or [])
    # The review header states what was read and what is uncertain. Corrupting it would test
    # whether the reviewer reads provenance, not whether it can find a false claim.
    body = next((i for i, ln in enumerate(md) if ln.strip() == "---"), 0) + 1
    used: set[int] = set(range(body))
    if only:
        # Scope the eval to one chapter's material: everything not citing it is off-limits.
        # Lets a run measure the reviewer on a slice you can check by hand, cheaply.
        cite = re.compile(rf'\[{re.escape(only)}\b')
        used |= {i for i in range(body, len(md)) if not cite.search(md[i])}
    misses: dict[str, int] = {}

    def pick(candidates: list[int]) -> int | None:
        free = [i for i in candidates if i not in used]
        return rng.choice(free) if free else None

    while len(defects) < n:
        kind = kinds[len(defects) % len(kinds)]
        line = after = None

        if kind == "polarity":
            pats = [(i, p, r) for i in range(len(md)) for p, r in POLARITY
                    if i not in used and re.search(p, md[i]) and md[i].lstrip().startswith(("-", "*", "|")) is False]
            if pats:
                i, p, r = rng.choice(pats)
                line, after = i, re.sub(p, r, md[i], count=1)
                hint = f"reversed: {p} -> {r}"

        elif kind == "number":
            if (i := pick(_lines_with(md, lambda ln: _NUM_RE.search(ln) and "|" not in ln))) is not None:
                m = rng.choice(list(_NUM_RE.finditer(md[i])))
                old = int(m.group(1))
                new = old + rng.choice([-100, -10, -3, -1, 1, 3, 10, 100])
                if new > 0 and new != old:
                    line = i
                    after = md[i][: m.start()] + str(new) + md[i][m.end():]
                    hint = f"figure {old} -> {new}"

        elif kind == "citation":
            if (i := pick(_lines_with(md, lambda ln: _LOCATOR_RE.search(ln)))) is not None:
                m = _LOCATOR_RE.search(md[i])
                others = [l for l in labels if l != m.group(1)]
                if others:
                    wrong = rng.choice(others)
                    line = i
                    after = md[i][: m.start()] + f"[{wrong} {m.group(2)}]" + md[i][m.end():]
                    hint = f"citation {m.group(1)} -> {wrong}"

        elif kind == "fabrication":
            if (i := pick(_lines_with(md, lambda ln: _SYNTH_MARKER_RE.search(ln)))) is not None:
                line = i
                after = _SYNTH_MARKER_RE.sub("", md[i])
                hint = "synthesis marker stripped — now reads as the book's claim"

        elif kind == "synthesis":
            # The class the reviewer is alone on. `fabrication` strips an existing marker and
            # is therefore capped by however many the summary happens to carry — one, in both
            # books. This one manufactures the defect instead: a cross-chapter claim the book
            # does not make, appended to a cited paragraph with no marker, which is the shape
            # `prompts/review.md` describes as most valuable and hardest to catch. Appending
            # rather than inserting a line keeps every recorded line number and the `used` set
            # valid; a real insert would shift both and silently mis-key every later defect.
            if unused_claims and (i := pick(_prose_targets(md, body))) is not None:
                claim = unused_claims.pop(rng.randrange(len(unused_claims)))
                line = i
                after = md[i].rstrip() + " " + claim
                hint = f"unmarked synthesis appended: {claim[:60]}"

        elif kind == "deletion":
            def _body_row(idx: int) -> bool:
                nxt = md[idx + 1] if idx + 1 < len(md) else ""
                return bool(_TABLE_ROW_RE.match(md[idx])) and not set(nxt.strip()) <= set("|-: ")
            if (i := pick([j for j in range(body, len(md)) if _body_row(j)])) is not None:
                line, after = i, None  # None means delete
                hint = f"table row removed: {md[i][:70]}"

        # A substitution that changed nothing is not a defect. Recording one puts an
        # uncatchable entry in the answer key and charges the reviewer for missing it, which
        # is a silent understatement of its recall — the failure this file exists to prevent,
        # turned on the file itself. `after is None` is deletion, which is a real change.
        if line is not None and after is not None and after == md[line]:
            used.add(line)  # burn the candidate; it can never yield a defect
            line = None

        if line is None:
            misses[kind] = misses.get(kind, 0) + 1
            if misses[kind] > 20:  # genuinely no candidates left for this class
                kinds = [k for k in kinds if k != kind]
                if not kinds:
                    break
            continue

        used.add(line)
        defects.append(Defect(len(defects) + 1, kind, line + 1, md[line], after or "", hint))
        md[line] = after if after is not None else "<<<DELETED>>>"

    return defects


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--part", help="only mutate lines citing this part, e.g. ch02")
    ap.add_argument(
        "--classes",
        default="polarity,number,citation,fabrication,deletion",
        help="comma-separated defect classes to inject",
    )
    args = ap.parse_args()

    book = corpus.load(args.slug)
    if not book.deep_path.is_file():
        print(f"no summary at {book.deep_path}", file=sys.stderr)
        return 2

    md = book.deep_path.read_text().splitlines()
    rng = random.Random(args.seed)
    labels = [p.label for p in book.in_scope]
    kinds = args.classes.split(",")
    claims = load_claims(book.slug) if "synthesis" in kinds else None
    defects = mutate(md, kinds, args.n, rng, labels, args.part, claims)

    out_dir = book.work_dir(ROOT) / "mutants"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{args.part + '-' if args.part else ''}s{args.seed}n{len(defects)}"
    mutant = out_dir / f"{book.slug}-{tag}.md"
    mutant.write_text("\n".join(ln for ln in md if ln != "<<<DELETED>>>") + "\n")

    key = out_dir / f"{book.slug}-{tag}.key.json"
    key.write_text(
        json.dumps(
            {
                "slug": book.slug,
                "seed": args.seed,
                "source": str(book.deep_path),
                "mutant": str(mutant),
                "defects": [asdict(d) for d in defects],
            },
            indent=2,
        )
    )

    by_kind: dict[str, int] = {}
    for d in defects:
        by_kind[d.kind] = by_kind.get(d.kind, 0) + 1
    print(f"{len(defects)} defects injected · " + " · ".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
    for d in defects:
        print(f"  #{d.id:<3} {d.kind:<12} line {d.line:<5} {d.hint[:80]}")
    print(f"\nmutant: {mutant}\nkey:    {key}")
    print("\nGive the reviewer the mutant and the rubric. Never the key.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
