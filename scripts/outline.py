#!/usr/bin/env python3
"""Draft a book's meta.json parts manifest from the PDF's embedded bookmarks.

    uv run python scripts/outline.py <slug> [--depth 1] [--write]

Writing the manifest by hand is the most tedious step in adding a book: transcribing page
ranges from the table of contents, then working out the offset between printed page
numbers and PDF page numbers. Both are mechanical, so neither should be done by hand.

The offset is inferred by extracting a spread of pages and reading the folio printed on
them; the most common (pdf_page - printed_page) difference wins. Always eyeball the
result — front matter, plates and multi-part books break the assumption of one constant
offset, and the script reports how confident the vote was.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

_CHAPTER_RE = re.compile(r"^\s*(?:chapter|ch\.?)\s*(\d+)\b[:.\s-]*", re.I)
_APPENDIX_RE = re.compile(r"^\s*appendix\s*([A-Z])\b[:.\s-]*", re.I)
_BARE_NUM_RE = re.compile(r"^\s*(\d{1,3})\s*$")
# "1 SIP and the Internet" — but not the section "1.2.1 Physical Layer".
_NUMBERED_TITLE_RE = re.compile(r"^\s*(\d{1,2})\s+(\S.*)$")
# The folio usually shares its line with a running header: "31    The Gist of Claude Code".
_FOLIO_LEAD_RE = re.compile(r"^\s*(\d{1,4})(?:\s|$)")
_FOLIO_TAIL_RE = re.compile(r"(?:^|\s)(\d{1,4})\s*$")


def label_for(title: str, seq: int) -> str:
    if m := _CHAPTER_RE.match(title):
        return f"ch{int(m.group(1)):02d}"
    if m := _APPENDIX_RE.match(title):
        return f"app{m.group(1).lower()}"
    return f"ch{seq:02d}"


def clean_title(title: str) -> str:
    title = _CHAPTER_RE.sub("", title)
    title = _APPENDIX_RE.sub("", title)
    return re.sub(r"\s+", " ", title).strip(" :-–—")


def bookmarks(pdf: Path) -> list[tuple[str, int, int]]:
    """Every bookmark as (title, 1-based pdf page, nesting level)."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    out: list[tuple[str, int, int]] = []

    def walk(items, level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(item) + 1  # 1-based, as pdftotext counts
            except Exception:  # noqa: BLE001 — malformed destinations are common
                continue
            out.append((str(item.title).strip(), page, level))

    walk(reader.outline, 0)
    return out


def _by_pattern(entries: list[tuple[str, int]], pattern: str | None) -> list[tuple[str, int]]:
    if not pattern:
        return []
    rx = re.compile(pattern, re.I)
    return [(t, p) for t, p in entries if rx.search(t)]


def _by_bare_number(entries: list[tuple[str, int]], _p: str | None) -> list[tuple[str, int]]:
    """Packt: a bare-number entry, with the chapter title as the next entry on the same page."""
    out: list[tuple[str, int]] = []
    for i, (title, page) in enumerate(entries):
        if not _BARE_NUM_RE.match(title):
            continue
        n = int(title.strip())
        follow = entries[i + 1][0] if i + 1 < len(entries) and entries[i + 1][1] == page else ""
        out.append((f"Chapter {n}: {follow}" if follow else f"Chapter {n}", page))
    return out


def _by_numbered_title(entries: list[tuple[str, int]], _p: str | None) -> list[tuple[str, int]]:
    """Artech/Wiley: "1 SIP and the Internet" — number and title in one entry.

    `\\d+\\s` cannot match a section like "1.2.1 Physical Layer", so this stays on chapters
    even when the level also holds sections. Appendices at the same level come along too,
    otherwise a book's back matter would be silently dropped from the manifest.
    """
    out = [
        (f"Chapter {int(m.group(1))}: {m.group(2)}", p)
        for t, p in entries
        if (m := _NUMBERED_TITLE_RE.match(t))
    ]
    if out:
        out += [(t, p) for t, p in entries if _APPENDIX_RE.match(t)]
    return sorted(out, key=lambda e: e[1])


def _by_prefix(entries: list[tuple[str, int]], _p: str | None) -> list[tuple[str, int]]:
    return [(t, p) for t, p in entries if _CHAPTER_RE.match(t) or _APPENDIX_RE.match(t)]


def _by_span(entries: list[tuple[str, int]], min_pages: int) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for i, (title, page) in enumerate(entries):
        end = entries[i + 1][1] if i + 1 < len(entries) else page + min_pages
        if end - page >= min_pages:
            out.append((title, page))
    return out


def select(marks: list[tuple[str, int, int]], min_pages: int, pattern: str | None) -> tuple[list[tuple[str, int]], str]:
    """Pick the bookmarks that are chapters, and say which rule and nesting level found them.

    A book's outline is rarely one clean level and never one convention. Packt PDFs are flat
    and mark a chapter with a bare-number entry; Artech nests chapters one level under the
    book title and writes "1 SIP and the Internet"; O'Reilly prefixes "Chapter N". So try the
    specific rules at every plausible depth before falling back to span length, which matches
    anything and therefore keeps front matter out only approximately.
    """
    by_level: dict[int, list[tuple[str, int]]] = {}
    for title, page, level in marks:
        by_level.setdefault(level, []).append((title, page))
    levels = sorted(by_level)[:3]  # chapters are rarely nested deeper than this

    for name, rule in (
        ("--pattern", _by_pattern),
        ("bare-number chapter markers", _by_bare_number),
        ("'N Title' chapter headings", _by_numbered_title),
        ("'Chapter N' / 'Appendix X' titles", _by_prefix),
    ):
        for level in levels:
            hits = rule(by_level[level], pattern)
            if len(hits) >= 3:
                return hits, f"{name} at outline level {level}"

    for level in levels:
        hits = _by_span(by_level[level], min_pages)
        if len(hits) >= 3:
            return hits, f"level-{level} entries spanning >= {min_pages} pages"
    return [], "no rule matched"


def detect_offset(pdf: Path, total: int, samples: int = 9) -> tuple[int | None, int, int]:
    """Vote on (pdf_page - printed_page) by reading the folio off a spread of pages."""
    votes: Counter[int] = Counter()
    checked = 0
    step = max(1, total // (samples + 1))
    for page in range(step * 2, total, step):
        try:
            text = subprocess.run(
                ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(pdf), "-"],
                capture_output=True,
                text=True,
                timeout=20,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            break
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            continue
        checked += 1
        for candidate in (lines[0], lines[-1], *lines[1:2], *lines[-2:-1]):
            m = _FOLIO_LEAD_RE.match(candidate) or _FOLIO_TAIL_RE.search(candidate)
            if not m:
                continue
            printed = int(m.group(1))
            if 0 < printed <= page:
                votes[page - printed] += 1
                break
    if not votes:
        return None, 0, checked
    offset, agree = votes.most_common(1)[0]
    return offset, agree, checked


def build(slug: str, pdf: Path, min_pages: int, pattern: str | None) -> dict:
    from pypdf import PdfReader

    total = len(PdfReader(str(pdf)).pages)
    all_marks = bookmarks(pdf)
    if not all_marks:
        raise SystemExit(f"{pdf} has no embedded bookmarks — write meta.json by hand")
    marks, rule = select(all_marks, min_pages, pattern)
    if not marks:
        raise SystemExit(f"{pdf}: no chapter-like bookmarks found among {len(all_marks)} — try --pattern")

    offset, agree, checked = detect_offset(pdf, total)
    rel = pdf.relative_to(corpus.BOOKS / slug)

    parts = []
    for i, (title, start) in enumerate(marks):
        end = marks[i + 1][1] - 1 if i + 1 < len(marks) else total
        part = {
            "label": label_for(title, i + 1),
            "title": clean_title(title),
            "file": str(rel),
            "pages": f"{start}-{max(start, end)}",
        }
        if offset is not None:
            part["printed_pages"] = f"{start - offset}-{max(start, end) - offset}"
        parts.append(part)

    meta = {
        "title": pdf.stem.replace("-", " ").replace("_", " ").title(),
        "authors": [],
        "publisher": "",
        "year": None,
        "isbn": "",
        "source": "",
        "licence": "copyrighted — local reference only, do not redistribute",
        "technical": True,
        "parts": parts,
    }
    if offset is not None:
        meta["pdf_page_offset"] = offset
    meta["_outline_note"] = (
        f"drafted by scripts/outline.py: {len(marks)} parts of {len(all_marks)} bookmarks "
        f"via {rule}; offset {offset} on {agree}/{checked} sampled pages"
        + ("" if offset is not None else "; OFFSET NOT DETECTED — fill in by hand")
    )
    return meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--pdf", default="source/book.pdf", help="path within the book directory")
    ap.add_argument("--pattern", help="regex selecting chapter bookmarks, when the heuristics miss")
    ap.add_argument("--min-pages", type=int, default=8, help="fallback rule: shortest a chapter can be")
    ap.add_argument("--write", action="store_true", help="write meta.json (backs up any existing one)")
    args = ap.parse_args()

    pdf = corpus.BOOKS / args.slug / args.pdf
    if not pdf.is_file():
        print(f"no PDF at {pdf}", file=sys.stderr)
        return 2

    meta = build(args.slug, pdf, args.min_pages, args.pattern)
    text = json.dumps(meta, indent=2, ensure_ascii=False)

    if not args.write:
        print(text)
        print(f"\n# {meta['_outline_note']}\n# re-run with --write to save", file=sys.stderr)
        return 0

    target = corpus.BOOKS / args.slug / "meta.json"
    if target.exists():
        backup = target.with_suffix(".json.bak")
        shutil.copy2(target, backup)
        print(f"backed up existing meta.json -> {backup}", file=sys.stderr)
    target.write_text(text + "\n")
    print(f"wrote {target}\n{meta['_outline_note']}", file=sys.stderr)
    print("Now fill in title/authors/publisher/isbn by hand, then run ingest.py.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
