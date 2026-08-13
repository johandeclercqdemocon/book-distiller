#!/usr/bin/env python3
"""Locate a book's figures and render the pages carrying them.

    uv run python scripts/figures.py <slug> [--parts ch04,ch16] [--figures 4.1,16.3]

Figure bodies are images or vector drawings and do not survive `pdftotext`; in a protocol
book the call-flow ladder diagrams are often the most valuable thing on the page. Extracting
the embedded rasters does not help — they are the icon glyphs inside a vector drawing, not
the drawing. So the page is rendered whole and read as an image by the distiller.

Page numbers are not parsed out of running headers. `pdftotext` separates pages with a form
feed, so splitting the extracted text on `\\f` maps content to PDF pages exactly, with no
heuristic to get wrong.

Writes work/<slug>/figures.json plus one PNG per page, and reports any requested figure it
could not find rather than passing over it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# "Figure 16.1 SIP-to-SIP call with proxies." — a caption. The text after the number starts
# a title, so it begins with a capital or a digit. A prose cross-reference instead continues
# a sentence ("Figure 16.1 shows...", "(see\nFigure 5.3) and occurs...") and starts lower-case
# or with punctuation. That one rule separates them; both counts are reported so a
# misclassification is visible rather than silent.
_CAPTION_RE = re.compile(r"^[ \t]*Figure[ \t]+(\d+\.\d+)[ \t]+([A-Z0-9][^\n]*)$", re.M)
_ANY_REF_RE = re.compile(r"^[ \t]*Figure[ \t]+(\d+\.\d+)", re.M)
_RANGE_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")


@dataclass
class Figure:
    id: str
    part: str
    caption: str
    pdf_page: int
    printed_page: int | None
    image: str | None = None


def page_texts(pdf: Path, first: int, last: int) -> dict[int, str]:
    """{pdf_page: text} for a page range, using form feeds as the page delimiter."""
    out = subprocess.run(
        ["pdftotext", "-layout", "-f", str(first), "-l", str(last), str(pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return {first + i: text for i, text in enumerate(pages)}


def part_pdf_range(part: dict) -> tuple[int, int] | None:
    if m := _RANGE_RE.search(str(part.get("pages", ""))):
        return int(m.group(1)), int(m.group(2))
    return None


def find_figures(book: corpus.Book, raw_parts: list[dict], wanted: set[str] | None) -> tuple[list[Figure], list[str], int]:
    offset = book.meta.get("pdf_page_offset")
    found: list[Figure] = []
    seen_refs: set[str] = set()
    refs_only = 0

    for part in raw_parts:
        rng = part_pdf_range(part)
        if not rng:
            continue
        pdf = corpus.BOOKS / book.slug / part["file"]
        if not pdf.is_file():
            continue
        for page, text in page_texts(pdf, *rng).items():
            for fid in _ANY_REF_RE.findall(text):
                seen_refs.add(fid)
            for fid, caption in _CAPTION_RE.findall(text):
                if wanted is not None and fid not in wanted:
                    continue
                if any(f.id == fid for f in found):
                    continue  # a caption repeated across a page break
                found.append(
                    Figure(
                        id=fid,
                        part=corpus.normalise_label(part["label"]),
                        caption=" ".join(caption.split()).rstrip("."),
                        pdf_page=page,
                        printed_page=page - offset if offset is not None else None,
                    )
                )
    refs_only = len(seen_refs - {f.id for f in found})
    missing = sorted(wanted - {f.id for f in found}) if wanted else []
    return sorted(found, key=lambda f: (f.part, [int(n) for n in f.id.split(".")])), missing, refs_only


def render(book: corpus.Book, figures: list[Figure], raw_parts: list[dict], dpi: int, context: int) -> None:
    by_label = {corpus.normalise_label(p["label"]): p for p in raw_parts}
    out_root = book.work_dir(ROOT) / "figures"
    for fig in figures:
        part = by_label[fig.part]
        pdf = corpus.BOOKS / book.slug / part["file"]
        first, last = fig.pdf_page - context, fig.pdf_page + context
        out_dir = out_root / fig.part
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = out_dir / f"fig-{fig.id}"
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(dpi), "-f", str(first), "-l", str(last), str(pdf), str(stem)],
            check=True,
            capture_output=True,
        )
        made = sorted(out_dir.glob(f"fig-{fig.id}-*.png"))
        fig.image = str(made[0].relative_to(ROOT)) if made else None


def render_pages(book: corpus.Book, raw_parts: list[dict], dpi: int) -> dict[str, int]:
    """Render every page of the selected parts.

    `pdftotext -layout` reflows dense material — in this corpus it has been caught folding one
    SIP message inside another — and drops every diagram. The page image is the only faithful
    record of what the page looks like, so the distiller gets both: text for character-exact
    verbatim content, images for layout, figures, and adjudication.
    """
    counts: dict[str, int] = {}
    for part in raw_parts:
        rng = part_pdf_range(part)
        if not rng:
            continue
        label = corpus.normalise_label(part["label"])
        pdf = corpus.BOOKS / book.slug / part["file"]
        if not pdf.is_file():
            continue
        out_dir = book.work_dir(ROOT) / "pages" / label
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(dpi), "-f", str(rng[0]), "-l", str(rng[1]), str(pdf), str(out_dir / "p")],
            check=True,
            capture_output=True,
        )
        counts[label] = len(list(out_dir.glob("p-*.png")))
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--parts", help="comma-separated part labels; default: parts with a `figures` scope in meta.json")
    ap.add_argument("--figures", help="comma-separated figure ids, e.g. 4.1,4.2,16.3")
    ap.add_argument("--all", action="store_true", help="every figure in the selected parts")
    ap.add_argument("--pages", action="store_true", help="also render every page of the in-scope parts")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--context", type=int, default=0, help="also render N pages either side (wide diagrams)")
    ap.add_argument("--dry-run", action="store_true", help="locate only, render nothing")
    args = ap.parse_args()

    book = corpus.load(args.slug)
    raw_parts = book.meta.get("parts", [])

    # Scope: explicit flags win, otherwise take each part's `figures` list from meta.json.
    wanted: set[str] | None = None
    if args.figures:
        wanted = {f.strip() for f in args.figures.split(",") if f.strip()}
    elif not args.all:
        wanted = set()
        for p in raw_parts:
            wanted.update(str(f) for f in p.get("figures", []))
        if not wanted:
            print("no `figures` scope in meta.json; pass --figures or --all", file=sys.stderr)
            return 2

    if args.parts:
        keep = {corpus.normalise_label(p) for p in args.parts.split(",")}
        raw_parts = [p for p in raw_parts if corpus.normalise_label(p["label"]) in keep]
    elif args.pages:
        raw_parts = [p for p in raw_parts if p.get("in_scope")]

    if args.pages and not args.dry_run:
        counts = render_pages(book, raw_parts, args.dpi)
        total = sum(counts.values())
        print("  " + " · ".join(f"{k} {v}p" for k, v in counts.items()))
        print(f"{total} pages rendered at {args.dpi} dpi -> work/{book.slug}/pages/\n")

    figures, missing, refs_only = find_figures(book, raw_parts, wanted)
    if not args.dry_run:
        render(book, figures, raw_parts, args.dpi, args.context)

    for fig in figures:
        printed = f"printed p.{fig.printed_page}" if fig.printed_page else "printed page unknown"
        print(f"  {fig.part}  Figure {fig.id:<6} pdf p.{fig.pdf_page:<4} {printed:<22} {fig.caption[:52]}")
    if missing:
        print(f"\n! requested but not found as a caption: {', '.join(missing)}", file=sys.stderr)
    print(
        f"\n{len(figures)} figures"
        + (f" rendered at {args.dpi} dpi" if not args.dry_run else " located (dry run)")
        + f" · {refs_only} figure numbers seen only as prose cross-references"
    )

    out = book.work_dir(ROOT) / "figures.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "slug": book.slug,
                "pdf_page_offset": book.meta.get("pdf_page_offset"),
                "dpi": args.dpi,
                "figures": [asdict(f) for f in figures],
                "requested_not_found": missing,
            },
            indent=2,
        )
    )
    print(f"wrote {out}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
