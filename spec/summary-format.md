# Summary format spec

Normative. `scripts/verify.py` enforces everything here mechanically; the adversary reviewer
enforces what cannot be mechanised. If the two disagree with this file, this file is wrong and
should be fixed — not worked around.

Two artifacts per book:

| File | Length | Purpose |
|---|---|---|
| `summaries/<slug>.md` | 8–12% of source words | the deep distillation; replaces reading the book |
| `summaries/<slug>-brief.md` | 1,200–1,800 words | stands alone; links into the deep file by section |

---

## 1. Locators

A **locator** ties a claim to the text it came from. It is the load-bearing element of the whole
format: it makes review possible, it makes verification mechanical, and it is what lets you go back
to the book for anything you are about to act on.

### Grammar

```
[ch07]                      the whole part
[ch07 p.142]                one printed page
[ch07 pp.142-146]           a printed page range
[ch07 p.142; ch09 p.201]    several sources, semicolon-separated
```

- The label must equal a `label` in the book's `meta.json` `parts` array. `verify.py` normalises
  `ch.7`, `ch7`, `CH07` → `ch07` and accepts a comma before `p.`, but emits a style warning. Canonical
  form is the bare one above.
- **Page numbers are printed pages** — the number on the paper page, not the PDF page. `verify.py`
  converts using `pdf_page_offset` / `page_offset` from `meta.json` and flags pages outside the
  part's range.
- A locator with an unknown label is **Critical**. That is an invented citation, the single most
  damaging defect this format can carry.

### Scope

A locator applies to the block it appears in. A heading may carry one, which then applies to every
block beneath it until the next heading of equal or higher level:

```markdown
### Hooks [ch04]

Hooks fire on five events.          ← inherits [ch04]

The `PreToolUse` event can block a call outright. [ch04 p.88]   ← overrides with a page
```

Prefer block-level locators with page numbers in the deep summary. Heading-level inheritance is for
sections that genuinely track one chapter end to end.

### What needs one

Every **claim block**: any paragraph, table, list, or fenced block that asserts something about the
world. Exempt:

- everything in the **front matter** — the title block and review header, up to and including the
  first `---` rule
- headings, horizontal rules, images
- blocks marked `<!-- nocite -->` (use sparingly; navigation text and section intros)
- **synthesis blocks** (§3), which carry a synthesis marker instead

---

## 2. Verbatim classes

These are copied character-for-character from the source. Never paraphrased, never "cleaned up",
never truncated with `...` unless the elision is marked.

- protocol messages and wire formats
- code and configuration
- grammars (ABNF, EBNF, regex)
- header-field, parameter and status-code tables
- state-transition tables
- command syntax and CLI flags
- error codes and their exact text

Mark them by putting the locator in the fence info string:

````markdown
```sip [ch03 p.44]
INVITE sip:bob@biloxi.com SIP/2.0
Via: SIP/2.0/UDP pc33.atlanta.com;branch=z9hG4bK776asdhds
Max-Forwards: 70
```
````

`verify.py` checks a marked block against the source with whitespace collapsed and pdftotext
hyphenation repaired. An unmarked fence is treated as illustrative and is not checked — so if it
came from the book, mark it.

Rationale: in a technical book the exactness *is* the content. A paraphrased SIP message or a
rounded-off timer value is not a summary of the fact, it is a different fact.

---

## 3. Synthesis must be fenced

Anything that is your reasoning rather than the book's claim is marked, in the block:

```markdown
**My construction, not the book's.** The book never puts these two together, but the failure mode
in ch.4 is the same one the ch.9 pattern is designed to prevent.
```

Or at section level: `### A decision table [synthesis]`.

This is not a formality. An unfenced synthesis is indistinguishable from a book claim at read time,
and it is the defect class that survives review most often because it reads well. It is **Major**
when found, and **Critical** if it contradicts the book.

---

## 4. Required structure of the deep summary

In order:

1. **Title block** — title, author, publisher, ISBN, page and word count, chapter count. One line on
   who the author is and why their view is worth having.
2. **Review header** — a blockquote recording: what was read and when, what the adversarial review
   checked, what it found and corrected, what it verified as accurate, the corpus `STATUS: untested`
   rule, the book's own caveats about its authority, and any dating risk.
3. `---`
4. **Section 0 — the one idea the book is built on.** If you cannot write this, the distillation is
   not finished.
5. **Body sections, organised by what the reader wants to do**, not by chapter order. Chapter order
   is the author's problem. Sections are named for tasks and questions.
6. **What the book does not cover** — its blind spots and where you would have to go instead.
7. **Chapter → topic index** — every part in `meta.json` appears here, mapping to the sections that
   drew on it. This is what makes coverage auditable by eye in thirty seconds.
8. **Identifier ledger** (technical books) — every header name, method, status code, RFC number,
   parameter, state and flag, with locator and a one-line definition. In a protocol book this is
   the single highest-value table in the file.
9. **Related** — links to other books in the corpus and to the projects this bears on.

## 5. Required structure of the brief

Title line, one paragraph on what the book is and who should read it, the central idea, 5–9 bullets
of the load-bearing findings each with a locator and a link to the deep section, and an explicit
"read the deep version when…" line. It must stand alone: someone who reads only the brief should
have no false beliefs, just fewer true ones.

---

## 6. Style rules that carry weight

- **Tables stay tables.** A table paraphrased into sentences loses the comparison, which was the
  point of the table.
- **Keep the number.** "Significantly faster" is a deletion. "3.2× faster on their benchmark
  [ch09 p.211]" is the fact.
- **Keep the author's hedge.** If the book says "in our experience" or "this is inferred from public
  posts, not official documentation", that qualifier travels with the claim. Stripping hedges is how
  a summary becomes more confident than its source, which is a fabrication of certainty.
- **Name the thing.** Prefer the book's own terminology, with the definition attached the first time.
- **Compression is declared.** A part deliberately covered thinly gets a line in the chapter index
  saying so and why. Never silence.

## 7. Machine-checked summary of the above

| Rule | Check in `verify.py` | Severity |
|---|---|---|
| Locator resolves to a real part | `locator.unknown_label` | Critical |
| Quoted string appears verbatim in the cited part | `quote.not_found` | Critical |
| Marked verbatim block matches source | `verbatim.mismatch` | Critical |
| Locator page inside the part's printed range | `locator.page_out_of_range` | Major |
| Multi-digit numeral appears in the cited part | `numeral.not_found` | Major |
| Backticked identifier appears in the cited part | `identifier.not_found` | Major |
| Every part cited at least once | `coverage.part_uncited` | Major |
| Summary newer than the digests it came from | `staleness.digest_newer` | Major |
| Claim block has a locator | `locator.missing` | Minor |
| Part's citation share ≥ 25% of its word share | `coverage.underweight` | Minor |
| Length inside the budget | `length.out_of_budget` | Minor |
| Canonical locator spelling | `locator.style` | Minor |
