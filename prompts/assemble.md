# Assemble a book's summary from its digests

You are building the deliverable. The digests are dense, chapter-shaped and over-inclusive by
design; your job is to turn them into something organised around what a reader wants to *do*,
without losing the detail that made the digests worth producing.

Read `spec/summary-format.md` first — it is the contract, and `scripts/verify.py` enforces
most of it mechanically. This file is the job.

## Inputs

- `work/<slug>/digests/*.md` — every digest. Read them all before writing anything.
- `~/reference/books/<slug>/meta.json` — per-part titles, printed page ranges, `scope`,
  `depth`, `dating_risk`, and which parts were in scope at all.
- `work/<slug>/digest_check.json` and `figures.json` — what was measured and what was rendered.

**Work from the digests, not the book.** You may open a specific page image or a passage of
chapter text to settle a contradiction the digests could not — that is what the locators are
for — but say so in the review header when you do. Re-reading whole chapters here defeats the
architecture and will not fit.

## Two artifacts

**`summaries/<slug>.md`** — the deep distillation. **`summaries/<slug>-brief.md`** — 1,200–1,800
words, standalone. Write the deep one first, then derive the brief from it; the brief is a
distillation of your own work, not a second pass over the digests.

**Build the deep summary section by section** — Write the file with its header and first
sections, then Edit to append the rest. Do not try to hold the whole document in one
generation. On a technical book the identifier ledger alone can run to hundreds of rows, and
composing everything in a single pass quietly pushes toward compression: the ledger comes out
thin, tables get summarised, and the retention this format exists to guarantee is the first
thing to go. Section by section, each one finished before the next, keeps that pressure off.

## Length

The budget is **8–12% of the in-scope source words**, and it governs **prose and synthesis
only**. The identifier ledger, reproduced tables, verbatim blocks and figure transcriptions
are copies, not compression — they are exempt and uncapped. On a protocol book the ledger
alone may exceed the prose. That is the format working.

Do not compute your own ratio. `verify.py` measures it.

## Organise by what the reader wants to do

Chapter order is the author's problem. Section the summary by task and question — how to read
a message, how routing actually works, what happens when it fails, how media gets negotiated
— and let each section draw on whichever chapters it needs. A section that maps one-to-one
onto a chapter is a sign you have transcribed the table of contents instead of reorganising it.

The required sections, in order, are in `spec/summary-format.md` §4. Two deserve emphasis:

**The identifier ledger** is, on a technical book, the single most valuable thing you produce.
Merge every identifier from every digest into one alphabetical table — name, kind, one-line
definition, locator. Deduplicate: the same header field defined in three chapters gets one row
citing the most complete definition, not three rows. Where chapters genuinely disagree about
what something does, that is a contradiction (below), not a duplicate.

**The chapter → topic index** must list every part in `meta.json`, including the ones that
were out of scope, marked as such. A reader needs to know what the summary does *not* cover
as much as what it does.

## Contradictions are your job

The digests recorded contradictions they were forbidden to resolve — figure against text,
prose against wire format, one chapter against another. You can see the whole book, so you
adjudicate:

- **Resolvable from evidence** — say which reading is right and why, and keep the wrong one
  visible in a note. Someone reading the book will hit it and needs to know it is a known
  defect, not their misunderstanding.
- **Not resolvable** — present both, say they conflict, and stop. Never silently pick the
  tidier one.
- **A printing defect in the book** is different from **damage from text extraction**. The
  digests distinguished them; preserve that distinction, because only the first is something
  a reader of the physical book will encounter.

## Fence your synthesis

Anything that is your construction rather than the book's is marked `**My construction, not
the book's.**` in the block, or `[synthesis]` on the heading. Connecting two chapters the
author never connected is valuable and welcome — an unlabelled one is indistinguishable from a
claim about the book and is the defect class that survives review most often because it reads
well.

The same applies to anything you know that the book does not say. Where a claim is
time-bound, flag it against `dating_risk` in `meta.json` — but as a marked note, never by
quietly correcting the text.

## Provenance

Where parts come from different editions or different sources, every claim must be traceable
to which. Carry the part's edition into the locator or the section note. A summary that
silently merges two editions of the same book is worse than one that covers only one edition,
because the reader cannot tell which decade a given claim describes.

## Keep

Numbers, table cells, exact identifiers, thresholds, wire syntax, and the author's own hedges.
"Significantly faster" is a deletion; "3.2× on their benchmark [ch09 p.211]" is the fact. If
the book says "in our experience", that qualifier travels with the claim — stripping it makes
the summary more confident than its source, which is a fabrication of certainty.

## The review header

The deep summary opens with the blockquote specified in `spec/summary-format.md` §4.2. Fill it
honestly: what was read and when, what is not covered and why, any contradiction you resolved
and on what basis, anything you opened the source to settle, the corpus `STATUS: untested`
rule, and the book's own caveats about its authority. This header is what a reader checks
before trusting anything below it.

## Finishing

Write both files, then run:

```
uv run python scripts/verify.py <slug> --max 0
```

Report what it says. Do not fix a finding by deleting the claim that triggered it — if a
number cannot be traced to its cited part, that is either a wrong locator or a wrong number,
and both need the digest consulted, not the sentence removed.
