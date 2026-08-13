"""Read-only access to the book corpus at ~/reference/books.

Nothing in this module writes to the corpus. Extraction is ingest.py's job; this is the
loading layer that verify.py and render.py share.

The corpus has two historical meta.json shapes and both are still in use:

  A  "pdf_page_offset": 38            parts have "printed_pages": "3-24"
  B  "page_offset": "printed page N = PDF page N + 18"   parts have "note": "Printed 1-14."

Both are normalised here to a single Part with a printed page range, so callers never
have to care which book they got.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

BOOKS = Path(os.environ.get("BOOK_CORPUS", Path.home() / "reference" / "books"))

_LABEL_RE = re.compile(r"^([a-z]+)[\s.\-_]*0*(\d+)$")
_RANGE_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")
_OFFSET_RE = re.compile(r"[+]\s*(\d+)")


def normalise_label(raw: str) -> str:
    """`ch.7`, `ch7`, `CH 07` -> `ch07`. Anything unrecognised passes through lowercased."""
    s = raw.strip().lower()
    m = _LABEL_RE.match(s)
    return f"{m.group(1)}{int(m.group(2)):02d}" if m else s


_SMART = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                        "–": "-", "—": "-", "−": "-", " ": " "})


def flatten(text: str, strip_markup: bool = False) -> str:
    """Normalise text for containment checks, on both sides of the comparison.

    pdftotext -layout pads with runs of spaces and keeps end-of-line hyphenation, so a phrase
    that reads as one string in the summary is several in the source. Typographic quotes and
    dashes differ between the two as well — this corpus prints curly quotes throughout.

    `strip_markup` additionally removes markdown emphasis and code ticks, for comparing a
    quotation written in markdown against plain source text: a summary quoting a line about
    `m=` lines carries backticks the book does not, and that is a formatting difference, not
    a misquotation.
    """
    text = re.sub(r"-\s*\n\s*", "", text).translate(_SMART)
    if strip_markup:
        text = re.sub(r"[`*_]+", "", text)
    return re.sub(r"\s+", " ", text)


@dataclass
class Part:
    label: str
    title: str
    text_path: Path
    printed_start: int | None = None
    printed_end: int | None = None
    in_scope: bool = True
    _raw: str | None = field(default=None, repr=False)

    @property
    def exists(self) -> bool:
        return self.text_path.is_file()

    @property
    def raw(self) -> str:
        if self._raw is None:
            self._raw = self.text_path.read_text(errors="replace") if self.exists else ""
        return self._raw

    @cached_property
    def flat(self) -> str:
        return flatten(self.raw, strip_markup=True)

    @cached_property
    def flat_lower(self) -> str:
        return self.flat.lower()

    @cached_property
    def words(self) -> int:
        return len(self.raw.split())

    @cached_property
    def numbers(self) -> set[str]:
        """Every numeric token in the part, comma-separators stripped.

        Both `64,534` and `64534` land as `64534` so a summary may format either way.
        """
        out: set[str] = set()
        for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", self.raw):
            out.add(tok.replace(",", ""))
            out.add(tok)
        return out

    def covers_page(self, page: int) -> bool | None:
        """True/False, or None when the book's metadata does not pin down a range."""
        if self.printed_start is None or self.printed_end is None:
            return None
        return self.printed_start <= page <= self.printed_end


@dataclass
class Book:
    slug: str
    meta: dict
    parts: list[Part]

    @property
    def dir(self) -> Path:
        return BOOKS / self.slug

    @property
    def title(self) -> str:
        return self.meta.get("title", self.slug)

    @property
    def technical(self) -> bool:
        return bool(self.meta.get("technical", False))

    @cached_property
    def by_label(self) -> dict[str, Part]:
        return {p.label: p for p in self.parts}

    @cached_property
    def in_scope(self) -> list[Part]:
        """Parts the current pass actually covers, or all of them if nothing is marked."""
        scoped = [p for p in self.parts if p.in_scope]
        return scoped or self.parts

    @cached_property
    def source_words(self) -> int:
        """Words in the parts being summarised — not the whole book.

        A summary of 9 of 17 chapters must be measured against those 9. Budgeting it against
        the full book would demand a summary half again as long as intended, and would count
        chapters nobody read.
        """
        return sum(p.words for p in self.in_scope)

    def part(self, raw_label: str) -> Part | None:
        return self.by_label.get(normalise_label(raw_label))

    # --- artifact paths -------------------------------------------------
    @property
    def deep_path(self) -> Path:
        return BOOKS / "summaries" / f"{self.slug}.md"

    @property
    def brief_path(self) -> Path:
        return BOOKS / "summaries" / f"{self.slug}-brief.md"

    def work_dir(self, root: Path) -> Path:
        return root / "work" / self.slug

    def digest_paths(self, root: Path) -> list[Path]:
        d = self.work_dir(root) / "digests"
        return sorted(d.glob("*.md")) if d.is_dir() else []


def _offset(meta: dict) -> int | None:
    """PDF page = printed page + offset."""
    raw = meta.get("pdf_page_offset", meta.get("page_offset"))
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        m = _OFFSET_RE.search(raw)
        if m:
            return int(m.group(1))
    return None


def _printed_range(part: dict, offset: int | None) -> tuple[int | None, int | None]:
    # Shape A: an explicit printed range.
    if m := _RANGE_RE.search(str(part.get("printed_pages", ""))):
        return int(m.group(1)), int(m.group(2))
    # Shape B: a note like "Printed 1-14."
    if m := _RANGE_RE.search(str(part.get("note", ""))):
        return int(m.group(1)), int(m.group(2))
    # Otherwise derive from the PDF range, if the book records an offset.
    if offset is not None and (m := _RANGE_RE.search(str(part.get("pages", "")))):
        return int(m.group(1)) - offset, int(m.group(2)) - offset
    return None, None


def load(slug: str) -> Book:
    meta_path = BOOKS / slug / "meta.json"
    if not meta_path.is_file():
        raise SystemExit(f"no meta.json for '{slug}' at {meta_path}")
    meta = json.loads(meta_path.read_text())
    offset = _offset(meta)
    parts = []
    for p in meta.get("parts", []):
        label = normalise_label(p["label"])
        start, end = _printed_range(p, offset)
        parts.append(
            Part(
                label=label,
                title=p.get("title", p.get("note", "")),
                text_path=BOOKS / slug / "text" / f"{p['label']}.txt",
                printed_start=start,
                printed_end=end,
                in_scope=bool(p.get("in_scope", True)),
            )
        )
    return Book(slug=slug, meta=meta, parts=parts)


def slugs() -> list[str]:
    return sorted(
        d.name for d in BOOKS.iterdir() if (d / "meta.json").is_file() and not d.name.startswith("_")
    )
