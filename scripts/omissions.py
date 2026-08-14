#!/usr/bin/env python3
"""Find what the summary dropped, by diffing it against the digests.

    uv run python scripts/omissions.py <slug> [--summary PATH]

Every other check reads the summary and asks whether what is there is true. This asks what is
*not* there — the one defect class a reader cannot catch by reading, and a reviewer cannot
catch by reasoning, because a deleted table row leaves no trace at all. It is a set
difference, so a script gets 100% recall where a model would be guessing.

Two comparisons, both grounded in the digests as the record of what the chapters contained:

  ledger   Identifiers recorded in any digest but absent from the summary's merged ledger.
           The ledger claims to be "merged across all parts", so an identifier missing from
           it is a broken promise, not an editorial choice.
  tables   Tables the summary reproduces that also exist in a digest, compared row by row on
           the first column. Fewer rows in the summary than in the digest is a dropped row.

These are candidates, not verdicts. A summary may legitimately compress — this book declares
ch06 at reference depth and ch16 compressed hardest — so the output is a worklist for the
reviewer, ranked by how load-bearing the missing thing looks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_H2_RE = re.compile(r"^##+\s+(.*)$")
_TABLE_CAP_RE = re.compile(r"\bTable\s+(\d+\.\d+)\b")
# Identifiers worth tracking carry structure — a header name, a code, a parameter. Prose
# fragments that happen to sit in a first column do not.
_IDENT_RE = re.compile(r"^[\w][\w./@:+-]*$")

# Things that look like identifiers to a regex but are worthless in a ledger. The baseline run
# on this book surfaced 133 candidates, most of them these: a summary is not expected to carry
# a ledger row for the example IP address in a printed INVITE.
_NOISE = (
    re.compile(r"^\d+$"),                       # bare numbers: 37129, 5060 as a value
    re.compile(r"^\d{1,3}(\.\d{1,3}){3}$"),     # IPv4 example addresses: 224.0.1.75
    re.compile(r"^[1-6]xx$"),                   # response-class shorthand, not a code
    re.compile(r"^\d+(\.\d+)+$"),               # section/table numbers: 4.1, 16.3
    re.compile(r"^v?\d+(\.\d+)*[a-z]?$"),       # version-ish tokens
    re.compile(r"^[a-z]$"),                     # stray single letters from column splits
)


def is_noise(key: str) -> bool:
    return any(p.match(key) for p in _NOISE)


def declared_depth(book: corpus.Book) -> dict[str, str]:
    """label -> the depth meta.json declares for it, for in-scope parts only.

    `depth: full` is a promise that nothing was deliberately left out, so an absence there is
    a silent loss. `depth: reference` (ch06 here) is a declared thinning, and its absences are
    the summary doing what it said it would.
    """
    return {
        corpus.normalise_label(p["label"]): str(p.get("depth", "full"))
        for p in book.meta.get("parts", [])
        if p.get("in_scope", True)
    }


def owning_part(table_number: str) -> str:
    """`Table 6.19` belongs to chapter 6 — the book numbers its tables by chapter."""
    return f"ch{int(table_number.split('.')[0]):02d}"


def accounted_numbers(md: str) -> set[str]:
    """Table numbers the summary accounts for without reproducing under that caption.

    `numbered_tables` only sees a table that kept its own caption. ch04's fourteen
    mandatory-header tables were legitimately merged into one matrix whose `Table` column cites
    each source number row by row — every cell the book's. Judged on captions alone that reads
    as fourteen losses, which is how a raw count turns a good editorial decision into an alarm.

    So: a number named in prose after the word "Table", or sitting in any table cell, counts as
    accounted for. It is a weaker claim than "reproduced" and deliberately so — it only says the
    summary did not drop the thing on the floor without a word.
    """
    found: set[str] = set()
    for line in md.splitlines():
        if "Table" in line or line.lstrip().startswith("|"):
            found.update(re.findall(r"\b(\d+\.\d+)\b", line))
    return found


def classify_absent(
    numbers: list[str], depths: dict[str, str], accounted: set[str]
) -> dict[str, list[str]]:
    """Split absent tables by how much worry each deserves.

    The raw count was the problem: 43 absent on this book read as catastrophic. Most sat either
    in a chapter the summary had *said* it was thinning, or in a merged matrix that cites them
    row by row. A number that cannot separate those from a real loss makes the reader discount
    all three.

    `unaccounted` is the only class that should stop a ship: a `depth: full` part promised
    nothing was left out, and the number appears nowhere in the summary at all.
    """
    out: dict[str, list[str]] = {
        "unaccounted": [], "accounted": [], "declared": [], "out_of_scope": []}
    for num in numbers:
        depth = depths.get(owning_part(num))
        if depth is None:
            out["out_of_scope"].append(num)
        elif depth != "full":
            out["declared"].append(num)
        elif num in accounted:
            out["accounted"].append(num)
        else:
            out["unaccounted"].append(num)
    return out


def norm(cell: str) -> str:
    """Compare identifiers on substance: strip markup, case and trailing punctuation."""
    return re.sub(r"[`*_]", "", cell).strip().strip(".,;:").lower()


def rows(lines: list[str]) -> list[list[str]]:
    out = []
    for ln in lines:
        if _SEP_RE.match(ln) or not (m := _ROW_RE.match(ln)):
            continue
        out.append([c.strip() for c in m.group(1).split("|")])
    return out


def section_lines(md: str, want: str) -> list[str]:
    out, taking = [], False
    for ln in md.splitlines():
        if m := _H2_RE.match(ln):
            taking = want in m.group(1).strip().lower()
            continue
        if taking:
            out.append(ln)
    return out


def digest_identifiers(digests: list[Path]) -> dict[str, tuple[str, str]]:
    """{normalised identifier: (display form, part label)} across every digest."""
    found: dict[str, tuple[str, str]] = {}
    for path in digests:
        label = path.stem
        for row in rows(section_lines(path.read_text(), "identifiers")):
            if not row:
                continue
            key = norm(row[0])
            if key and key not in found and _IDENT_RE.match(key) and len(key) > 1 and not is_noise(key):
                found[key] = (row[0].strip(), label)
    return found


def index_rows(md: str) -> set[str]:
    """Part labels listed in the chapter -> topic index."""
    out: set[str] = set()
    for row in rows(section_lines(md, "index")):
        if row and (k := norm(row[0])) and re.match(r"^[a-z]+\d+$", k):
            out.add(corpus.normalise_label(k))
    return out


def numbered_tables(md: str) -> dict[str, set[str]]:
    """{table number: first-column keys}, for tables actually reproduced.

    Find the tables first, then look for their number — not the other way round. Caption style
    and position both vary: the digests write `### Table N.M` above the rows, the summary
    writes "Table 5.1, cell for cell." *below* them, and a passing prose mention has no rows
    near it at all. Scanning for captions therefore fails on one format or the other, and
    treating every mention as a caption credits unrelated rows to whichever table was named
    last. A contiguous run of `|` lines is unambiguous; the number is whichever `Table N.M`
    sits closest to it on either side.
    """
    lines = md.splitlines()
    blocks: list[tuple[int, int, list[str]]] = []
    i = 0
    while i < len(lines):
        if _ROW_RE.match(lines[i]):
            j = i
            while j < len(lines) and (_ROW_RE.match(lines[j]) or _SEP_RE.match(lines[j])):
                j += 1
            blocks.append((i, j, lines[i:j]))
            i = j
        else:
            i += 1

    def nearby_number(start: int, end: int) -> str | None:
        """The closest `Table N.M` within three non-blank lines above or below the block."""
        for offset in range(1, 6):
            for idx in (start - offset, end - 1 + offset):
                if 0 <= idx < len(lines) and (m := _TABLE_CAP_RE.search(lines[idx])):
                    return m.group(1)
        return None

    tables: dict[str, set[str]] = {}
    for start, end, body in blocks:
        num = nearby_number(start, end)
        if not num:
            continue
        # Drop the header row: markdown puts it immediately before the `|---|` separator, and
        # counting it both inflates the row count and invents a missing row whenever two
        # documents word their headers differently ("Class" vs "Class [ch05 p.112]").
        rows_only = body[2:] if len(body) > 1 and _SEP_RE.match(body[1]) else body
        keys = {k for ln in rows_only if not _SEP_RE.match(ln)
                for k in [norm(ln.strip().strip("|").split("|")[0])] if k}
        if keys:
            tables.setdefault(num, set()).update(keys)
    return tables


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--summary", type=Path, help="override, e.g. a mutant under work/")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument(
        "--baseline",
        type=Path,
        help="an earlier omissions.json — report only what this run lost that it did not",
    )
    args = ap.parse_args()

    book = corpus.load(args.slug)
    summary_path = args.summary or book.deep_path
    if not summary_path.is_file():
        print(f"no summary at {summary_path}", file=sys.stderr)
        return 2
    digests = book.digest_paths(ROOT)
    if not digests:
        print("no digests to compare against", file=sys.stderr)
        return 2

    md = summary_path.read_text()
    ledger = {norm(r[0]) for r in rows(section_lines(md, "identifier ledger")) if r}
    in_digests = digest_identifiers(digests)
    missing = sorted(k for k in in_digests if k not in ledger)

    d_tables: dict[str, set[str]] = {}
    for path in digests:
        for num, keys in numbered_tables(path.read_text()).items():
            d_tables.setdefault(num, set()).update(keys)
    s_tables = numbered_tables(md)
    # A table the summary reproduces can be compared row by row. A table it never reproduces
    # at all was invisible to this check until r2 of sip-johnston, where three whole tables
    # from full-depth chapters went missing and only the adversary noticed. A wholly absent
    # table is the worse defect of the two: a short table leaves a stub to notice, an absent
    # one leaves nothing.
    absent_tables = sorted(set(d_tables) - set(s_tables), key=lambda n: [int(x) for x in n.split(".")])
    dropped_rows = {
        num: sorted(d_tables[num] - keys)
        for num, keys in s_tables.items()
        if num in d_tables and (d_tables[num] - keys)
    }

    missing_parts = sorted(p.label for p in book.parts if p.label not in index_rows(md))

    base = json.loads(args.baseline.read_text()) if args.baseline else None
    if base:
        known = {x["identifier"] for x in base.get("missing_identifiers", [])}
        new_missing = [k for k in missing if in_digests[k][0] not in known]
        known_parts = set(base.get("parts_not_indexed", []))
        new_parts = [p for p in missing_parts if p not in known_parts]

    print(f"\n{book.title}  [{book.slug}]")
    print(f"summary: {summary_path.name} · {len(digests)} digests")
    if base:
        print(f"baseline: {args.baseline.name} — reporting only what is newly absent")

    shown = new_missing if base else missing
    print(f"\nledger: {len(ledger)} rows · digests hold {len(in_digests)} distinct identifiers")
    print(
        f"        {len(shown)} {'newly ' if base else ''}absent from the ledger"
        + (f" ({len(missing)} total)" if base else "")
    )
    for k in shown[: args.max]:
        display, label = in_digests[k]
        print(f"          {display:<28} {label}")
    if len(shown) > args.max:
        print(f"          … {len(shown) - args.max} more")

    depths = declared_depth(book)
    absent_by_kind = classify_absent(absent_tables, depths, accounted_numbers(md))
    unaccounted = absent_by_kind["unaccounted"]
    print(f"\ntables: {len(s_tables)} numbered tables reproduced · {len(dropped_rows)} with rows missing"
          f" · {len(absent_tables)} without their own caption")
    print(f"        {len(unaccounted)} UNACCOUNTED (a `depth: full` part, named nowhere) · "
          f"{len(absent_by_kind['accounted'])} cited elsewhere · "
          f"{len(absent_by_kind['declared'])} declared thin · "
          f"{len(absent_by_kind['out_of_scope'])} out of scope")
    for num in unaccounted[: args.max]:
        print(f"          Table {num}: UNACCOUNTED — {owning_part(num)} is `depth: full` and the "
              f"summary never names it ({len(d_tables[num])} rows in the digests)")
    for num in absent_by_kind["accounted"][: args.max]:
        print(f"          Table {num}: cited but not reproduced under its own caption "
              f"({len(d_tables[num])} rows)")
    for num, keys in sorted(dropped_rows.items()):
        print(f"          Table {num}: {len(keys)} row(s) — {', '.join(keys[:6])}")

    idx_shown = new_parts if base else missing_parts
    print(f"\nindex:  {len(idx_shown)} part(s) {'newly ' if base else ''}absent from the chapter index")
    for label in idx_shown:
        part = book.by_label[label]
        print(f"          {label}  {part.title[:44]:<46}{'in scope' if part.in_scope else 'out of scope'}")

    out = args.json or book.work_dir(ROOT) / "omissions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "summary": str(summary_path),
                "ledger_rows": len(ledger),
                "digest_identifiers": len(in_digests),
                "missing_identifiers": [
                    {"identifier": in_digests[k][0], "part": in_digests[k][1]} for k in missing
                ],
                "dropped_table_rows": dropped_rows,
                "absent_tables": {n: sorted(d_tables[n]) for n in absent_tables},
                "absent_tables_by_kind": absent_by_kind,
                "parts_not_indexed": missing_parts,
            },
            indent=2,
        )
    )
    print(f"\nwrote {out}")
    print("Candidates, not verdicts — a summary may compress deliberately. Rank before acting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
