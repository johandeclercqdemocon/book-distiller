#!/usr/bin/env python3
"""Measure a digest against its source chapter. Deterministic; no model involved.

    uv run python scripts/digest_check.py <slug> [label ...]

The distiller used to report its own counts and got them wrong in both directions — a
4,464-word chapter reported as "~6,400", a 9,987-word digest reported as "~3,050". Asking a
model to compute its own compression ratio is asking it to do bookkeeping, which is what
scripts are for. The prompt now says "be over-inclusive"; this says whether it was.

Definitions that matter:

  copied     Verbatim blocks, reproduced tables, the identifier ledger, and figure
             transcriptions. Not compression, so not budgeted — there is no such thing as
             copying 20% of a wire format.
  reasoning  The Claims, hedges and open-question sections, minus any fenced blocks inside
             them. This is what the 15-20% floor governs: how hard the explanation around
             the artifacts was compressed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REASONING = {"claims", "author's hedges", "hedges", "open questions for assembly", "open questions"}
FLOOR = 0.15  # reasoning words as a share of the source chapter

_FENCE_RE = re.compile(r"^(```|~~~)")
_H2_RE = re.compile(r"^##\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+\S")
_LOCATOR_RE = re.compile(r"\[(?:[a-zA-Z]+\d+\s+)?pp?\.\s*\d+")
_FIG_RE = re.compile(r"Figure\s+(\d+\.\d+)")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def sections(md: str) -> dict[str, list[str]]:
    """Split on `## ` headings, keeping deeper headings inside their parent section."""
    out: dict[str, list[str]] = {"": []}
    current = ""
    for line in md.splitlines():
        if m := _H2_RE.match(line):
            current = m.group(1).strip().lower()
            out.setdefault(current, [])
            continue
        out[current].append(line)
    return out


def split_fenced(lines: list[str]) -> tuple[list[str], list[str]]:
    """(prose, fenced) — fenced content is copied material, never compression."""
    prose, fenced, in_fence = [], [], False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        (fenced if in_fence else prose).append(line)
    return prose, fenced


def words(lines: list[str]) -> int:
    return sum(len(ln.split()) for ln in lines)


def claim_blocks(lines: list[str]) -> tuple[list[str], list[str]]:
    """(all claims, claims with no locator anywhere in them).

    A claim is a bullet plus its indented continuation lines, and the locator usually lands
    at the end of the last one — so the whole block has to be tested, not the opening line.
    A locator on the enclosing `###` heading counts too: heading scope is part of the
    locator grammar in spec/summary-format.md, not a loophole.
    """
    blocks: list[str] = []
    heading_cited = False
    current: list[str] | None = None

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append(("HEADINGCITED " if heading_cited else "") + " ".join(current))
        current = None

    for line in lines:
        if line.startswith("#"):
            flush()
            heading_cited = bool(_LOCATOR_RE.search(line))
            continue
        if _BULLET_RE.match(line):
            flush()
            current = [line]
        elif current is not None and line.strip():
            current.append(line)
        elif current is not None:
            flush()
    flush()
    return blocks, [b for b in blocks if not b.startswith("HEADINGCITED") and not _LOCATOR_RE.search(b)]


def check(book: corpus.Book, label: str, inventory: Mapping[str, list[dict]]) -> tuple[dict, list[str]]:
    digest_path = book.work_dir(ROOT) / "digests" / f"{label}.md"
    part = book.by_label.get(label)
    md = digest_path.read_text()
    secs = sections(md)
    problems: list[str] = []

    reasoning = fenced_in_reasoning = 0
    for name, lines in secs.items():
        if name in REASONING:
            prose, fenced = split_fenced(lines)
            reasoning += words(prose)
            fenced_in_reasoning += words(fenced)

    total = words(md.splitlines())
    source = part.words if part else 0
    share = reasoning / source if source else 0.0

    claim_lines, uncited = claim_blocks(secs.get("claims", []))

    ident_rows = [
        ln for ln in secs.get("identifiers", []) if _TABLE_ROW_RE.match(ln) and not set(ln) <= set("|- :\t")
    ]
    fig_lines = secs.get("figures", [])
    transcribed = {m.group(1) for ln in fig_lines if "TRANSCRIBED" in ln.upper() and (m := _FIG_RE.search(ln))}
    gaps = {m.group(1) for ln in fig_lines if "GAP:" in ln.upper() and (m := _FIG_RE.search(ln))}

    expected = {f["id"] for f in inventory.get(label, [])}
    unaccounted = sorted(expected - transcribed - gaps)

    if source and share < FLOOR:
        problems.append(f"reasoning is {share:.0%} of the chapter (floor {FLOOR:.0%}) — compressed too hard")
    if uncited:
        problems.append(f"{len(uncited)} claim bullets carry no page locator")
    if unaccounted:
        problems.append(f"figures rendered but absent from the digest: {', '.join(unaccounted)}")
    if gaps:
        problems.append(f"{len(gaps)} figure(s) recorded as GAP though a page image exists: {', '.join(sorted(gaps))}")
    if not claim_lines:
        problems.append("no claim bullets found — check the digest's section headings")

    return (
        {
            "label": label,
            "source_words": source,
            "digest_words": total,
            "reasoning_words": reasoning,
            "reasoning_share": round(share, 4),
            "copied_words": total - reasoning - fenced_in_reasoning,
            "claims": len(claim_lines),
            "claims_without_locator": len(uncited),
            "identifiers": max(0, len(ident_rows) - 1),  # drop the header row
            "figures_expected": len(expected),
            "figures_transcribed": len(transcribed),
            "figures_gap": len(gaps),
            "problems": problems,
        },
        problems,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("labels", nargs="*", help="default: every digest present")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    book = corpus.load(args.slug)
    digest_dir = book.work_dir(ROOT) / "digests"
    labels = args.labels or [p.stem for p in sorted(digest_dir.glob("*.md")) if "." not in p.stem]
    if not labels:
        print(f"no digests in {digest_dir}", file=sys.stderr)
        return 2

    inventory: dict[str, list[dict]] = {}
    fig_json = book.work_dir(ROOT) / "figures.json"
    if fig_json.is_file():
        for fig in json.loads(fig_json.read_text()).get("figures", []):
            inventory.setdefault(fig["part"], []).append(fig)

    rows, failed = [], 0
    print(f"\n{book.title}  [{book.slug}]")
    print(f"{'part':<8}{'source':>8}{'digest':>8}{'reason':>8}{'share':>7}{'claims':>8}{'no-loc':>7}{'ids':>6}{'figs':>9}")
    for label in labels:
        row, problems = check(book, label, inventory)
        rows.append(row)
        figs = f"{row['figures_transcribed']}/{row['figures_expected']}"
        if row["figures_gap"]:
            figs += f"+{row['figures_gap']}gap"
        print(
            f"{label:<8}{row['source_words']:>8,}{row['digest_words']:>8,}{row['reasoning_words']:>8,}"
            f"{row['reasoning_share']:>6.0%}{row['claims']:>8}{row['claims_without_locator']:>7}"
            f"{row['identifiers']:>6}{figs:>9}"
        )
        for p in problems:
            print(f"        ! {p}")
        failed += bool(problems)

    print(f"\n{len(rows)} digest(s) · {failed} with problems")
    out = args.json or book.work_dir(ROOT) / "digest_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))
    print(f"wrote {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
