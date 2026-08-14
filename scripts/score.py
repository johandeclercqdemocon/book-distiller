#!/usr/bin/env python3
"""Score a review against a mutation key: what did the reviewer actually catch?

    uv run python scripts/score.py <key.json> <review.md> [--label opus-xhigh]

`mutate.py` breaks a summary in known ways. This says how many of those breaks came back,
per defect class, so the choice of reviewer model is a measurement rather than an argument.

**Per-class recall is the number that matters, not the total.** A reviewer that catches every
invented citation and no reversed rule scores 50% and is close to useless — the citations were
already caught for free by `verify.py`, while a reversed rule is the defect that reaches the
reader intact. Read the table, never the headline.

Matching is deliberately generous: a finding counts as a catch if it cites the mutated line,
or quotes enough of it, or names the identifier the defect turned on. Recall is what is being
measured, and a stingy matcher would flatter the reviewer by turning its near-misses into
false negatives of this script instead.

Precision is reported too but is not a verdict. A "false positive" here may be a real defect
in the underlying summary that the mutation run happened to surface — this book had four
unresolved quote failures and sixteen adjudicated contradictions before anyone mutated it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_LINE_REF_RE = re.compile(r"\b(?:line|L|l\.)\s*(\d{1,5})\b")
_WORD_RE = re.compile(r"[A-Za-z0-9_./:-]{3,}")
_STOP = {
    "the", "and", "that", "this", "with", "from", "for", "not", "but", "are", "was", "its",
    "which", "when", "must", "may", "can", "will", "has", "have", "one", "two", "into", "than",
    "then", "them", "they", "their", "there", "these", "those", "some", "each", "only", "also",
}
NEAR = 2  # a finding may cite a line this far off and still count


def shingles(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text)} - _STOP


# A finding's own label: `**C1 — …`, `### M2.`, `minor 3:`. Case is significant and must not
# be folded — this project's reports use `M1` for Major and `m1` for Minor.
_ID_SHORT_RE = re.compile(r"^[#>\s]*\**\s*([CMm])\s*[-–—.:)\s]?\s*(\d{1,3})\b")
_ID_LONG_RE = re.compile(r"^[#>\s]*\**\s*(critical|major|minor)\s*[-–—.:)#\s]?\s*(\d{1,3})\b", re.I)
_SEV_COUNT_RE = re.compile(r"(\d+)\s+(critical|major|minor)", re.I)


def _finding_id(line: str) -> str | None:
    for rx in (_ID_SHORT_RE, _ID_LONG_RE):
        if m := rx.match(line):
            return f"{m.group(1)}{m.group(2)}"
    return None


def findings_section(md: str) -> tuple[list[str], int]:
    """The lines of the report's findings section, and the offset they start at.

    Everything after it — triage adjudication, coverage, what could not be settled — is prose
    *about* the review, not findings. Counting it was what made the precision column meaningless:
    a report with 15 findings scored as though it had 60-odd, most of them unmatched by
    construction.
    """
    lines = md.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        if not (m := re.match(r"^##\s+(.*)$", line)):
            continue
        title = m.group(1).strip().lower()
        if start is None:
            if title.startswith("finding") and "by severity" not in title:
                start = i + 1
            continue
        return lines[start:i], start
    return (lines[start:], start) if start is not None else (lines, 0)


def findings(md: str) -> list[dict]:
    """Split a review into findings, one per labelled item.

    Splitting on *any* markdown item boundary over-splits badly: a single finding is a label
    plus several evidence bullets, so it became four or five "findings". Recall survived that
    (each fragment is matched independently and a defect needs one hit) but precision did not,
    because the denominator was fragments.

    So the label is the boundary. Where a report uses no labels, fall back to the old generous
    rule *within the findings section* — over-splitting there is still better than missing a
    finding, and `declared_counts` will show the disagreement.
    """
    body, offset = findings_section(md)
    out: list[dict] = []
    current: list[str] = []
    start = 0
    fid: str | None = None
    for i, line in enumerate(body):
        if new := _finding_id(line):
            if current:
                out.append({"line": offset + start + 1, "text": " ".join(current), "id": fid})
            current, start, fid = [line.strip()], i, new
        elif current:
            current.append(line.strip())
    if current:
        out.append({"line": offset + start + 1, "text": " ".join(current), "id": fid})

    if not out:  # unlabelled report — generous fallback, confined to the findings section
        for i, line in enumerate(body):
            if re.match(r"^\s*(#{1,6}\s|\d+[.)]\s|[-*]\s)", line) and current:
                out.append({"line": offset + start + 1, "text": " ".join(current), "id": None})
                current, start = [], i
            current.append(line.strip())
        if current:
            out.append({"line": offset + start + 1, "text": " ".join(current), "id": None})

    return [f for f in out if len(f["text"].split()) >= 4]


def declared_counts(md: str) -> dict[str, int]:
    """The severity tally the report states about itself, from its closing line.

    The review prompt requires the report to end with its own count, which makes it a free
    check on this splitter: if the two disagree, one of them is wrong and the precision figure
    should not be read until it is known which.
    """
    tail = "\n".join(md.splitlines()[-12:])
    return {sev.lower(): int(n) for n, sev in _SEV_COUNT_RE.findall(tail)}


def matches(defect: dict, finding: dict) -> tuple[bool, str]:
    """Does this finding identify this defect? Returns (hit, why)."""
    text = finding["text"]

    for m in _LINE_REF_RE.finditer(text):
        if abs(int(m.group(1)) - defect["line"]) <= NEAR:
            return True, f"cites line {m.group(1)}"

    before, after = defect.get("before", ""), defect.get("after", "")
    flat = " ".join(text.split()).lower()
    for snippet in (before, after):
        s = " ".join(snippet.split()).lower()
        if len(s) > 40 and (s[:60] in flat or s[-60:] in flat):
            return True, "quotes the mutated text"

    # The distinctive tokens of the mutated line — for a deletion, the row that vanished.
    # For an append (`synthesis`), nothing was removed, so that difference is empty and this
    # branch could never fire; fall back to what the mutation *added*.
    key_tokens = shingles(before) - shingles(after) or shingles(after) - shingles(before)
    if len(key_tokens) >= 3 and len(key_tokens & shingles(text)) >= max(3, len(key_tokens) // 3):
        return True, "names the mutated content"

    if defect["kind"] == "citation":
        if m := re.search(r"(ch\d{2})\s*->\s*(ch\d{2})", defect["hint"]):
            if m.group(2) in text.lower() and re.search(r"\bcit|\blocator|\bwrong chapter", text, re.I):
                return True, "flags the wrong citation"

    if defect["kind"] == "number":
        if m := re.search(r"figure (\d+) -> (\d+)", defect["hint"]):
            if m.group(2) in text:
                return True, "flags the altered figure"

    return False, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key", type=Path)
    ap.add_argument("review", type=Path)
    ap.add_argument("--label", default="", help="what produced this review, e.g. the model")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    key = json.loads(args.key.read_text())
    defects = key["defects"]

    # A defect whose `after` equals its `before` was never written to the mutant. Scoring
    # against one silently understates recall: the reviewer is charged for missing a line
    # that is identical to the source. Keys written before mutate.py guarded this contain
    # them; refuse rather than report a number that is quietly wrong.
    if noop := [d for d in defects if d.get("after", "") == d.get("before", "")
                and d.get("kind") != "deletion"]:
        print(f"{args.key}: {len(noop)} defect(s) leave the line unchanged and cannot be "
              f"found by anyone: {', '.join(f'id {d['id']} ({d['kind']} L{d['line']})' for d in noop)}\n"
              f"Regenerate the mutant, or drop these entries from the key.", file=sys.stderr)
        return 2

    found = findings(args.review.read_text())

    caught: dict[int, dict] = {}
    used: set[int] = set()
    for d in defects:
        for n, f in enumerate(found):
            hit, why = matches(d, f)
            if hit:
                caught[d["id"]] = {"finding_line": f["line"], "why": why}
                used.add(n)
                break

    by_kind: dict[str, list[int]] = {}
    for d in defects:
        by_kind.setdefault(d["kind"], []).append(d["id"])

    label = args.label or args.review.stem
    print(f"\n{label}  ·  {args.key.name}")
    print(f"{'class':<14}{'caught':>8}{'of':>4}{'recall':>9}")
    for kind, ids in sorted(by_kind.items()):
        hit = sum(1 for i in ids if i in caught)
        print(f"{kind:<14}{hit:>8}{len(ids):>4}{hit / len(ids):>8.0%}")
    total = len(caught)
    print(f"{'TOTAL':<14}{total:>8}{len(defects):>4}{total / len(defects):>8.0%}")

    missed = [d for d in defects if d["id"] not in caught]
    if missed:
        print(f"\nmissed ({len(missed)}):")
        for d in missed:
            print(f"  #{d['id']:<3} {d['kind']:<12} line {d['line']:<5} {d['hint'][:70]}")

    extra = len(found) - len(used)
    review_md = args.review.read_text()
    declared = declared_counts(review_md)
    print(f"\n{len(found)} findings · {len(used)} matched a known defect · {extra} did not")
    if len(found):
        print(f"precision {len(used) / len(found):.0%} — read the caveat below before using it")
    if declared:
        total_declared = sum(declared.values())
        shape = " · ".join(f"{v} {k}" for k, v in declared.items())
        agree = "agrees" if total_declared == len(found) else "DISAGREES"
        print(f"report declares {total_declared} ({shape}) — splitter {agree}")
        if total_declared != len(found):
            print("  precision is not trustworthy until that gap is explained: the splitter is")
            print("  either merging findings or counting something that is not one.")
    print("Unmatched findings are not necessarily wrong — check a sample against the source")
    print("before treating them as noise; the summary had real defects before it was mutated.")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "label": label,
                    "key": str(args.key),
                    "review": str(args.review),
                    "total": {"caught": total, "of": len(defects)},
                    "by_kind": {
                        k: {"caught": sum(1 for i in ids if i in caught), "of": len(ids)}
                        for k, ids in by_kind.items()
                    },
                    "caught": caught,
                    "missed": [d["id"] for d in missed],
                    "unmatched_findings": extra,
                },
                indent=2,
            )
        )
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
