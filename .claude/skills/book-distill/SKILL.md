---
name: book-distill
description: How to distil a book into a reviewed markdown summary — the pipeline stages, where files live, and which spec governs each step. Use when working on a digest, summary, review, or the corpus in this repo.
---

# Distilling a book

Six stages. Code does the bookkeeping; the model does the judgment. Full rationale is in
`PLAN.md`; this is the operating procedure.

| # | Stage | Run with | Reads | Writes |
|---|---|---|---|---|
| 0 | Ingest | `uv run python scripts/outline.py <slug>` then corpus `ingest.py` | `source/book.pdf` | `meta.json`, `text/*.txt` |
| 1 | Distill | `/distill <slug> --all` | one chapter per subagent | `work/<slug>/digests/*.md` |
| 2 | Assemble | `/assemble <slug>` | all digests | `summaries/<slug>{,-brief}.md` |
| 3 | Verify | `uv run python scripts/verify.py <slug>` | summary + source | `work/<slug>/verify.json` |
| 4 | Review | `/adversary <slug>` | summary, digests, rubric | `work/<slug>/review-r<N>.md` |
| 5 | Render | `uv run python scripts/render.py <slug>` | summary | `summaries/<slug>.pdf` |

## Which file governs what

- `spec/digest-format.md` — the per-chapter claim ledger.
- `spec/summary-format.md` — locator grammar, verbatim classes, required sections, and the
  table of what `verify.py` checks mechanically.
- `rubric/summary-rubric.md` — how the adversary scores, with worked examples from real
  defects.
- `prompts/*.md` — the stage prompts. Agents include these rather than inlining them, so a
  later API runner uses the same text. Edit the prompt file, never the agent.

## Rules worth repeating here

**Never distil a chapter in the main conversation.** Delegate to the `distiller` subagent.
A chapter read here stays in context and is re-sent on every later turn; read in a subagent,
it is paid for once.

**Never let the reviewer share context with the author.** The adversary is a subagent with
read-only tools for exactly this reason.

**Run `verify.py` before any model review.** It is free and it catches the mechanical
defects — invented citations, figures that don't exist, uncited chapters — so the reviewer's
attention goes to judgment instead of counting.

**The corpus is read-only to this project** except for the two summary files and the PDF.
`text/` is evidence: a model that can edit its evidence can make any finding go away.

## Before trusting output

`README.md` has a **Known issues** section listing the checks that misfire and why —
`verify.py`'s two false Criticals on quote normalisation, `omissions.py`'s proximity-based
table attribution, and the retired `contradicted` verdict. Read it before acting on a finding.

## Adding a book, end to end

```bash
mkdir -p ~/reference/books/<slug>/source && cp <book>.pdf $_/book.pdf
uv run python scripts/outline.py <slug> --write        # drafts meta.json from bookmarks
# fill in title/authors/isbn/technical by hand from the copyright page, then:
python3 ~/reference/books/_scripts/ingest.py <slug>    # extracts text/
uv run python scripts/figures.py <slug> --pages        # renders page images
```

Check the detected `pdf_page_offset` against a real page before trusting it: an off-by-one
shifts every chapter and silently drops each one's opening page. That happened to four books
in this corpus and was only caught by comparing a printed folio against its PDF page.
