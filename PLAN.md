# book-distiller — plan

**Goal:** ingest a book, produce a markdown distillation dense enough that reading it makes you
genuinely smarter about the subject — details, numbers and caveats included, not an abstract —
then have an adversarial reviewer subagent try to break it before it ships.

Decided 2026-08-07: Claude Code now with prompts factored for a later API runner · reviewer gates
and drives an auto-revise loop · reuses `~/reference/books` and extends its ingestion · two output
artifacts (brief + deep) · most targets are deeply technical books · the deep artifact also ships as
a printable A4 PDF with a contents list, page numbers and a back-of-book index.

---

## 1. What we are actually building against

The request contains a tension worth naming: *summary* implies compression, *nitty gritty* implies
retention. The deliverable is not a summary in the usual sense — it is a **replacement for reading
the book**. Two failure modes destroy that, and every design decision below exists to fight one of
them.

**F1 — compression loss.** The default LLM summarization failure: the generic survives, the
specific dies. Table cells, thresholds, exact config keys, the author's own hedges, the one number
that makes a claim actionable. What is lost is precisely what would have made you smarter.

**F2 — drift and fabrication.** Detail that *reads* as book-derived but is not: a rule stated
backwards, a figure transposed, a synthesis presented as the author's position. Worse than
omission, because it is invisible at read time and you will act on it.

There is already evidence for both on disk. `summaries/agentic-coding-claude-marco.md` (6,117 words
from a 64,534-word book) was adversarially reviewed on 2026-08-06 and twelve discrepancies were
found — one substantive (the `memory/` placement rule stated backwards), one material (a claim that
the book solved a problem it does not solve), and one whole chapter missing. That file is both the
proof this workflow catches real errors and the reference implementation for the output format.

## 2. Architecture

Code lives in a git repo at `~/claude/book-distiller/`. Data never does — input stays in
`~/reference/books/<slug>/{source,text,meta.json}`, output goes to
`~/reference/books/summaries/<slug>{,-brief}.md`, intermediates to `work/<slug>/`. The corpus stays
outside git on purpose and that does not change.

```
                    deterministic                      model
  source/*.pdf ──▶ 0. ingest ──▶ text/*.txt ──▶ 1. distill (map, per part, parallel)
                                                        │
                                            work/<slug>/digests/*.md   ← dense claim ledger
                                                        │
                                                 2. assemble (reduce)
                                                        │
                                    summaries/<slug>.md + <slug>-brief.md
                                                        │
                        3. verify (deterministic, no model) ──▶ verify.json
                                                        │
                                        4. adversary subagent (fresh context)
                                                        │
                                            work/<slug>/review-r1.md
                                                        │
                            5. revise ──▶ re-review ──▶ gate: zero Critical
```

### Stage 0 — ingest (no model)

Extends the existing `~/reference/books/_scripts/ingest.py` rather than replacing it.

- **`scripts/outline.py`** (new): read the PDF's embedded bookmarks and emit a draft `meta.json`
  `parts` manifest, including the printed→PDF page offset inferred by extracting one page and
  matching its printed folio. This removes the most tedious manual step in the current procedure
  (hand-transcribing page ranges from the ToC). Needs `pypdf` — not currently installed; the repo
  gets a `pyproject.toml` and runs under `uv`.
- **EPUB**: `ebook-convert` (calibre) is not installed either. Either install calibre, or accept
  PDF-only. Recommendation: PDF-only for now, EPUB when a book actually needs it — the corpus is
  100% PDF today.
- Extraction itself stays `pdftotext -layout`, which is present and works.

### Stage 1 — distill (map)

One subagent invocation per part, each with a **clean context holding one chapter, not a book**.
Output: `work/<slug>/digests/<label>.md`.

The digest is *not* prose. It is a dense claim ledger at roughly 15–20% of the part: every claim,
every figure, every table reproduced whole, every named identifier, each with a locator
`[ch07 p.142]`. Its job is to be over-inclusive — pruning happens at assembly, where the whole book
is visible and you can tell what is load-bearing.

Why an intermediate at all: a 350-page book is ~200k tokens. It *fits*, but a single pass over it
summarizes the middle badly, and F1 is exactly what that failure looks like. Chapter-scoped reading
keeps fidelity high where the text is actually being read; assembly then reasons over ~40k tokens of
pre-filtered claims instead of the raw book. Parts are independent, so these runs parallelize.

### Stage 2 — assemble (reduce)

One pass over all digests, producing two artifacts:

- **`summaries/<slug>.md`** — the deep distillation, ~10% of source words, organised **by what you
  want to do**, not by chapter. (The Marco summary's structure — "How to structure a project",
  "Hooks", "Choosing between a pipeline and an agentic project" — is why it is usable. Chapter order
  is the author's problem, not the reader's.)
- **`summaries/<slug>-brief.md`** — ~1,500 words, stands alone, section-links into the deep file.

Format rules, specified in `spec/summary-format.md` and enforced downstream:

1. Every factual line carries a locator. Uncited line = a finding.
2. Synthesis is fenced explicitly (`**my construction, not the book's**`). Non-negotiable — it is
   the difference between a reference and a plausible-sounding hazard.
3. The author's own hedges and caveats survive into the summary. If the book says its account is
   inferred from blog posts rather than official sources, the summary says so too.
4. A "what the book does not cover" section, and a chapter→topic index, so coverage is auditable by
   a human in thirty seconds.
5. Tables are reproduced, not paraphrased into sentences.
6. Corpus rule inherited unchanged: a book claim is a hypothesis. Nothing here graduates into
   your project's empirical-findings file without a real run.

### Stage 3 — verify (no model)

`scripts/verify.py` runs *before* the reviewer, so the reviewer spends its attention on judgment
rather than bookkeeping. Model does judgment; code does counting.

| Check | Catches |
|---|---|
| Locator well-formed and resolves to a real part | invented citations |
| **Every numeral in the summary appears in the cited part's text** | transposed and invented figures — cheap, high yield |
| Every quoted string appears verbatim in source | fabricated quotes |
| Each part in `meta.json` cited ≥ N times; zero-coverage parts listed | dropped chapters (the Marco run lost ch.5 entirely) |
| Word count vs. source, per artifact | silent drift off the depth target |
| Every identifier-shaped token resolves in the cited part | wrong status codes, invented header names, bad RFC numbers |
| Verbatim blocks match source character-for-character | paraphrased protocol messages, code and grammar |
| Figure inventory fully accounted for in digests | diagrams silently dropped by `pdftotext` |
| Digest mtime vs. summary mtime | summary built from stale digests |

Writes `work/<slug>/verify.json`. Hard failures block stage 4.

### Stage 4 — adversarial review

`.claude/agents/adversary.md` — **read-only tools** (Read, Grep, Glob), fresh context, and never the
context that wrote the summary. Isolation is the whole point: a reviewer that shares context with
the author is grading its own homework.

Its brief is falsification, not appreciation. Three rules make it work:

- **Every finding must quote the summary line and the source line, with locators. No evidence, no
  finding.** This is the single most important control — an unconstrained critic hallucinates
  objections as readily as an unconstrained author hallucinates claims.
- **Bounded but non-uniform sampling.** It cannot re-read the book. It checks: everything
  `verify.json` flagged; every table and every numeric claim; a sample of N claims per chapter; and
  the ★-priority chapters in full.
- **It grades omission too.** It holds the digests, so it can ask what the summary dropped that a
  reader needs. This is where "nitty gritty" is actually defended — F1 is otherwise invisible to a
  reviewer that only reads the summary.

Severity: **Critical** (false claim, reversed meaning, invented citation) · **Major** (load-bearing
detail dropped, synthesis passed off as the book's) · **Minor** (imprecision, structure).
Output: `work/<slug>/review-r<N>.md` — per-dimension scores plus findings.

### Stage 5 — revise and gate

Revision pass applies Critical and Major findings, and **records findings it rejected with reasons**
— the reviewer is not infallible and a silently-ignored finding is a bug in the audit trail. Then
re-review. Gate: zero Critical ships. Cap at 3 rounds, then stop and report rather than loop.

The accumulated rounds become the header block of the final summary, exactly as in the Marco file:
what was checked, what was found, what was corrected, what was verified accurate.

### Stage 6 — the print edition (no model)

The deep summary is meant to be read on paper, so `scripts/render.py` produces an A4 PDF beside the
markdown. Markdown stays the source of truth; the PDF is a view of it.

- **A4**, 20/18mm margins, serif body at 10.5pt, running header carrying the current section, page
  number in the bottom margin.
- **Contents** with dot leaders and page numbers, built from the headings.
- **Back-of-book index** built automatically from every backticked identifier, with page references.
  On a protocol book this is the table you actually use six months later, and it costs nothing to
  produce because the identifiers are already marked up.
- **PDF bookmarks** from the heading levels, for on-screen navigation.

Every page number — contents, index, footer — is resolved by the layout engine at render time, so
none of them can drift from the text. Nothing is hand-numbered and no model is involved.

Implemented with WeasyPrint, which supports the CSS Paged Media features this needs
(`@page` margin boxes, `string-set`, `leader()`, `target-counter()`, `bookmark-level`). It installs
through `uv` against the system pango already present on Ubuntu 24.04 — no LaTeX, no pandoc, no apt.

### Technical books are the hard case, and the default case

Most targets will be deeply technical — protocol and systems books like Johnston's SIP book, where
the value is in header fields, message flows, state machines, RFC cross-references and exact
syntax. A prose-summarizer pointed at that produces something worse than useless: fluent, plausible,
and wrong in the details that are the entire point. Five specific adjustments:

**1. Verbatim classes.** The format spec defines content that must be reproduced exactly, never
paraphrased: protocol message listings, code, ABNF/grammar, header-field tables, state-transition
tables, command syntax, error codes. A paraphrased SIP message is a lie about a wire format. The
distiller copies these into the digest character-for-character, and `verify.py` checks them back
against the source.

**2. Figures are not in the text.** `pdftotext` drops every image-based figure, and in a protocol
book the call-flow ladder diagrams often *are* the chapter. Silent loss is exactly F1. So:
`scripts/figures.py` scans extracted text for figure captions, builds a per-part figure inventory,
and renders those PDF pages to PNG with `pdftoppm` (present). The distiller **reads the page images**
for figure-heavy pages and transcribes each diagram into text — a ladder diagram becomes an ordered
message list, a state diagram becomes a transition table. Any figure it cannot transcribe is
recorded as an explicit gap, never omitted quietly. `verify.py` fails if the inventory has figures
with no corresponding digest entry.

**3. An identifier ledger.** Per book: every header name, method, status code, RFC number, parameter,
state name and CLI flag encountered, with its locator and one-line definition. Built during distill,
carried into the deep summary as a lookup table. This is the highest-value artifact in a protocol
book and it is precisely what free-form summarization destroys.

**4. Identifier fidelity check.** `verify.py` gains a check alongside the numeral check: every
token matching an identifier shape in the summary (`RFC \d+`, `[45]\d\d` status codes, `Header-Case`
names, `snake_case`/`--flags`) must appear in the cited part's text. Catches `481` written for `408`
and invented header names, which are the most damaging and least visible errors in this genre.

**5. Rubric weighting shifts.** For books flagged `technical: true` in `meta.json`, Retention and
Fidelity dominate the score, and a single wrong identifier or wrong status code is **Critical**, not
Minor — in a protocol reference, a plausible wrong constant is worse than an omission, because you
will act on it. The adversary's full-read set expands to every part containing verbatim classes.

Cost consequence: page-image reading is not free. Figures are rendered and read only for pages the
inventory flags, not the whole book.

## 3. The rubric

`rubric/summary-rubric.md`, versioned, five dimensions — each with **concrete pass/fail examples
lifted from the Marco summary and its twelve real findings**. Worked examples over abstract
criteria: that is already a tested finding in your own the downstream project work (precision rules need
examples), and it applies to a grader prompt as much as to a voice prompt.

1. **Fidelity** — no claim unsupported by its cited text; no reversed meaning.
2. **Retention** — figures, table cells, identifiers, thresholds survive. Scored against the digests.
   On technical books this dimension and Fidelity dominate, and a wrong identifier is Critical.
3. **Coverage** — every part represented in proportion to its content.
4. **Honesty** — synthesis fenced, author's hedges kept, gaps stated, dating risk flagged.
5. **Usability** — task-organised, navigable, any claim traceable to source in under a minute.

## 4. Testing the grader, not just the summary

An ungraded grader is the actual risk here, and you have already been bitten by exactly this —
`grade.py` silently discarding ~15% of runs (C16) was found only because someone checked the
checker.

**Mutation testing.** Take a finished, human-approved summary. Programmatically inject known
defects — flip a number, reverse a rule, invent a citation, delete a table row, promote a synthesis
line to an unfenced claim. Run the adversary. Measure catch rate per defect class.

`agentic-coding-claude-marco` is the golden case: the summary exists, is human-reviewed, and its
header records twelve real historical defects to seed the mutation set with. Target: 100% on
invented citations and flipped numbers (these are mechanically detectable — if the adversary misses
them, `verify.py` should have caught them and the pipeline has a hole), and a measured, honest
number on reversed-meaning and dropped-detail, which are the hard classes.

## 5. Repo layout

```
~/claude/book-distiller/
  CLAUDE.md                    short, imperative: locators mandatory, synthesis fenced,
                               corpus rule, never write to EMPIRICAL_FINDINGS
  .claude/
    agents/     distiller.md · adversary.md (read-only) · reviser.md
    commands/   distill.md · review.md · book-status.md
    skills/book-distill/SKILL.md + references/
    settings.json              committed permissions, so the run is not a prompt storm
  scripts/      outline.py · ingest.py (extends corpus copy) · verify.py · mutate.py
  spec/         summary-format.md · digest-format.md
  rubric/       summary-rubric.md
  prompts/      distill.md · assemble.md · review.md   ← standalone, reused verbatim by the
                                                          future Python/API runner
  evals/        marco golden case, mutation set, results
  work/         per-book intermediates (gitignored)
  pyproject.toml
```

Prompts and rubrics live in plain files that the agent definitions *include* rather than inline.
That is what makes "Claude Code now, API later" real rather than aspirational: the later runner
loads the same files, and the two implementations cannot drift.

## 6. Build order

| Phase | Contents | Testable by |
|---|---|---|
| 1 ✅ | Repo skeleton, CLAUDE.md, format spec, rubric, `verify.py`, `outline.py`, `render.py` | Done 2026-08-07 — see below |
| 2 ✅ | `distiller` agent + `/distill` + `figures.py`, target `sip-johnston` | Built 2026-08-07 — see below |
| 3 ✅ | Assemble stage, both artifacts, `digest_check.py` | Built 2026-08-07; not yet run |
| 4 | `adversary` + rubric + revise loop | Full run on `prompt-engineering-for-llms-berryman-ziegler` (87k words, 11 parts, already extracted) |
| 4b | `figures.py`, identifier ledger, verbatim classes, technical rubric weighting | First run on the Johnston SIP book once it is in the corpus |
| 5 | `mutate.py` + eval run; tune the rubric against catch rates | Measured catch rate per defect class |
| 6 | *Later:* Python/API runner over the same prompt files | Same outputs from both drivers |

Phase 1 is entirely deterministic and bills no inference. Phases 2–5 do.

### Phase 1 results, 2026-08-07

Built and run against the corpus. Setup and config reference: `SETUP.md`.

**`verify.py` on `summaries/agentic-coding-claude-marco.md`** — 0 critical, 14 major, 112 minor. The
majors that matter:

- Six chapters carry no citation at all. Their *content* is present and correctly placed in the
  chapter index — this is a citation gap, not a coverage gap, and it is why the two are separate
  checks. Under the new spec that summary would not ship as-is.
- `[ch.2, p.592-603]` cites pages that do not exist in a 376-page book.
- Four identifiers cited to ch.5 — `/install-github-app`, `.github/workflows/claude.yaml`,
  `claude-code-review.yaml`, `claude/issue/<issue-number>` — appear **nowhere** in any extracted
  chapter. That is the drift class: specific, plausible, and not from the book.
- The summary writes `memory/frontend/CLAUDE.md`; the source says `frontend/CLAUDE.md`. This is the
  same `memory/` placement claim that the 2026-08-06 human review already caught and corrected once.

**`outline.py` recovered all three Packt manifests exactly** — 12, 16 and 13 parts, matching the
hand-written `meta.json` files — using a "bare-number bookmark followed by the chapter title"
heuristic, since these PDFs have flat outlines of 369–752 entries.

**It also found an off-by-one in the corpus.** The detected page offsets are 29 / 37 / 31; the
hand-written `meta.json` files say 30 / 38 / 32. Verified directly: PDF page 60 of the Marco book
prints folio 31, and its chapter-2 bookmark is on PDF page 48 — but `meta.json` extracts ch02 from
PDF 49-72. So **every extracted chapter in these three books is missing its own first page and
carrying the first page of the next chapter**. The chapter's framing paragraph is usually on that
page. Fixing it means correcting the offsets and re-running `ingest.py --force`, which rewrites
`text/` — the user's data, so it needs an explicit go-ahead.

### Phase 2 results, 2026-08-07

Built: `prompts/distill.md`, the `distiller` subagent, `/distill`, the `book-distill` skill,
and `scripts/figures.py` — the last pulled forward from phase 4b, because the target book
made it a blocker rather than a refinement.

**Target changed to `sip-johnston`**, ingested this session: Alan B. Johnston, *SIP:
Understanding the Session Initiation Protocol*, 3rd ed. 2009, Artech House, 427 pages,
17 chapters, 113,146 words. Offset 31, verified against a printed folio. `slp3` was dropped
as the phase-2 smoke test: a linguistics chapter has no wire formats, header tables or
ladder diagrams, so it would have validated the prompt against none of the things the
technical-book design exists for.

**`outline.py` needed a second fix.** This book nests chapters at outline level 1 (level 0
is the book title) and titles them `1 SIP and the Internet` — neither handled by the
level-0-only selector. `select()` now tries each rule at every plausible depth and reports
which rule and level fired. All four Packt books still resolve identically.

**Scope, agreed with the user:** 9 of 17 chapters — ch02, ch03, ch04, ch05, ch06, ch10,
ch12, ch13, ch16 — 68,743 words, 61% of the book. Security (ch14) dropped entirely. A
4th-edition *Media Security* chapter will be scanned from print and added as its own part.
Per-part `in_scope` / `depth` / `scope` / `figures` fields now live in `meta.json`, which
settles open question #1: chapter 6 is `depth: reference` (ledger every header field, prose
only for the ones carrying behaviour).

**The edition finding.** The user's chapter list named "SIP Security and Identity" and
"Media Security" — neither exists in this edition, and SRTP/DTLS appear here in ch17
*Future Directions*. That is good evidence their earlier summary came from the 4th edition,
and it is why the corpus now needs per-part edition provenance: one book directory is about
to hold content from two editions, and a claim that silently merges them is exactly the
defect this project exists to prevent.

**Figures work.** Extracting embedded rasters is useless — `pdfimages` on ch16 returns 24
duplicated 64×58 icon glyphs, because the ladder diagrams are vector drawings. Rendering the
page with `pdftoppm` is faithful. Page mapping needs no folio parsing: `pdftotext` separates
pages with a form feed, so splitting on `\f` maps content to PDF pages exactly. All 17
requested figures (ch04 4.1–4.12, ch16 16.1–16.5) located and rendered at 150 dpi,
900×1350 px, ~1,620 visual tokens each. Zero missing. The caption-vs-cross-reference rule —
a caption's text starts with a capital or digit, a prose reference continues a sentence —
correctly excluded 81 prose references, including a phantom "Figure 5.3" inside ch04.
Figure 16.1 renders legibly enough to read all four actors, both servers, and all 24
messages M1–M24.

**Tables need no rendering at all** — they survive `pdftotext` intact, caption and columns
included. So the requested header tables cost nothing beyond the text pass; only line
drawings need images. That cut the figure budget from ~210k visual tokens for the whole book
to ~28k, and the distill stage for the selection to roughly $1.40.

**`render.py`** produced a 29-page A4 PDF from the 6,117-word Marco summary: contents with dot
leaders and resolved page numbers, running headers, footer page numbers, styled tables, PDF
bookmarks, and a two-column index of 100+ identifiers with page references.

## 6b. Triage: the result that justifies the layer, 2026-08-10

First full run — `triage.py --kind ledger --backend anthropic`, 234 of 246 ledger rows (the
other 12 carry no page-specific locator), Haiku 4.5, 8 parallel: **200 supported, 25 unclear,
6 contradicted, 3 absent.** About four minutes and $0.25.

Two flags confirmed against the page images as real defects:

- **`Subject`** — the ledger says "not used by the protocol". Page 145 says it *"can be used
  by UAs for simple call screening"*. Verified against the page; stands.
- **`64*T1` was a false positive, and mine.** I called it a confirmed scope reversal after
  reading the INVITE paragraph on page 67 alone. The non-INVITE paragraph nine lines above
  gives the same bound — *"continued until a 64\*T1, after which the request is declared
  dead"* — so the ledger's "INVITE or not" is correct. The error then propagated into the
  triage prompt as its worked example of "contradicted", which plausibly taught the model to
  over-flag scope differences. Corrected 2026-08-10; the example is now `Subject`.

**The `Subject` defect is not reachable by anything else in the pipeline.** `verify.py` sees a resolvable
locator and a real page; `omissions.py` sees a present row; a sampling reviewer would have had
to happen upon that one row out of 246. This is the argument for triage existing: not cost,
not speed — *coverage of a defect class that only a per-claim read can find*.

Two known weaknesses, both fixable and neither invalidating:

- **The one-page window inflates `unclear`.** Almost every unclear note reads "confirms X but
  does not mention Y" — the ledger merges definitions across chapters and cites the page with
  the fullest one, so supporting detail legitimately sits elsewhere. Widen to the locator's
  full range, or ±1 page.
- **`contradicted` is over-applied.** Of six, three are substantive, one is an overstatement,
  and two are omissions wearing the wrong label. Split "the page says the opposite" from "the
  page does not mention this" in the prompt.

Backend comparison stands at 0.95 units/sec on Haiku against 0.02 on a local 8B on CPU — ~48×,
for ~$1.15 across all 1,276 units versus roughly eighteen hours. The Ollama path stays for one
accuracy comparison on the same 50 rows; it is not the cheaper option in any sense that matters.

## 6c. Two findings from the first complete cycle, 2026-08-11

`sip-johnston` went ingest -> distill -> assemble -> verify -> review -> revise -> re-review.
Round 2 returned SHIP, 0 Critical: the r1 Critical (a reversed Content-Length adjudication)
was fixed and verified consistent across §1, §11 and the ledger, restored tables matched the
source byte for byte, and the summary grew rather than shrank. Two findings outlast that run.

### The severity ranking is backwards for this project

Round 2 shipped with three silent retention losses — Table 6.2 (31 rows), Table 12.1 (8 rows)
and ch12 §12.3 Compression — all from chapters marked `depth: full`, none declared. It shipped
because `rubric/summary-rubric.md` grades "load-bearing detail dropped" as **Major** and
fabrication as **Critical**, and the stopping rule gates on Criticals alone.

That inherits a ranking from general summarisation, and it is wrong here. **A fabrication has a
second line of defence and a silent omission does not.** `verify.py` catches invented
citations, fabricated quotes and untraceable numerals mechanically; nothing catches a table
that was never written, and a reader cannot notice an absence. §1 of this plan names that as
F1 and calls it the reason the project exists — then the rubric grades it below the failure the
scripts already cover.

**Change before the next book:** on a `technical: true` book, an undeclared omission from a
part marked `depth: full` is Critical. Declared compression stays Minor — the distinction the
format already draws between silence and a stated choice is exactly the right line.

### Triage's `contradicted` verdict should be retired, not tuned

Precision across three measured rounds: **22% -> 17% -> 2.6%** — by round 3, 38 dismissals per
confirmation. Two rounds of prompt tightening (a same-meaning test, a mandatory two-phrase
`conflict` field, then removing it from the actionable set) did not arrest the decline.

The failures share one shape across every round, and it is the same error I made by hand on
`64*T1`: **reading one window and treating a page break as a disagreement.** That is not a
prompt defect. It is what a bounded per-claim check *is*, and no wording fixes it — the
adversary finds this class properly because it reads whole pages and searches the chapter.

What the layer actually earns its place on is **citation quality**: `absent` and `incomplete`
held up in every round, because "these pages do not discuss this" is a judgement a single
window can honestly make, and a wrong locator is a real defect. Keep those; drop the verdict
that promised the most and delivered least.

**The generalisable lesson:** a cheap layer should be given the questions its narrow view can
answer, not the questions you most want answered.

## 7. Cost and constraints

- **Inference cost per book.** For a 350-page book (~200k tokens of text): distill ~250k in / 60k
  out, assemble ~80k in / 25k out, review ~150k in / 15k out, and the loop can double the last two.
  Order of 0.5–1M input tokens per complete book cycle. Worth knowing before pointing it at
  `30-agents-ahmad` (157k words).
- **Missing tooling:** `pypdf` (needed by `outline.py`), and `calibre` only if EPUB is wanted.
  `pdftotext`, `pdftoppm` and `pdfimages` are all present, so figure rendering needs nothing new.
- **The Johnston SIP book is not in the corpus yet** — no `johnston` slug under `~/reference/books`.
  It needs adding (`source/`, `meta.json`) before it can be a target.
- **Outputs stay local.** Same as the rest of the corpus — derived work from copyrighted sources,
  not for redistribution.
- **Corpus rule unchanged:** everything produced here is `STATUS: untested` until a real run
  confirms it.

## 8. Open questions

- **Book-specific priorities.** The Marco summary is good partly because a human decided which
  chapters mattered. Proposal: a `priority` field per part in `meta.json` (★ / ★★), which drives
  digest depth and the adversary's full-read set. Small change, large effect on both quality and cost.
- **Coverage floor.** Should a chapter the model judges low-value still be represented? Proposal:
  yes, always at least one line plus a note saying why it was compressed — silent omission is the
  failure this project exists to prevent.
