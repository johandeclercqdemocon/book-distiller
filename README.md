# book-distiller

Turns a book into a markdown distillation dense enough to replace reading it — details,
numbers, tables and the author's own caveats intact — then has an adversarial reviewer try to
break it before it ships.

Not a summary in the usual sense. The target reader wants to come back in six months and look
something up, so the failure this fights hardest is the one where a summary reads well and has
quietly dropped the thing that made a claim actionable.

**Status:** working. One book has been through the complete cycle — *SIP: Understanding the
Session Initiation Protocol* (Johnston, 3rd ed., 427 pages), 9 of 17 chapters, 68,743 source
words → a **25,596-word summary** (66 pages as an A4 PDF) with a 246-row identifier ledger and
chapter 16's five call flows transcribed from rendered page images. Two adversarial review
rounds plus two targeted restoration passes. Six phases built; see `PLAN.md` for the design
and what each one found.

## Quickstart

Two drivers run the same prompts. Read `prompts/*.md` once — that is where the actual
instructions live, not in the agent definitions or the scripts.

**Claude Code** (interactive; use this when a book is being worked on):

```bash
cd ~/claude/book-distiller && claude
```

Then `/distill <slug> --all`, `/assemble <slug>`, `/adversary <slug> --revise`.

**Python** (batch; use this across many books):

```bash
./scripts/withkey uv run python scripts/run.py distill <slug>
```

`withkey` loads `ANTHROPIC_API_KEY` from `~/.bashrc` into the child process only — `.bashrc`
returns early in non-interactive shells, so the key is otherwise unset, and exporting it
globally would shadow Claude Code's OAuth login and move billing to the API.

## The pipeline

| # | Stage | Run with | Cost |
|---|---|---|---|
| 0 | Ingest | `scripts/outline.py`, corpus `ingest.py`, `scripts/figures.py --pages` | free |
| 1 | Distill | `/distill <slug> --all` — one subagent per chapter | ~$1.40 |
| 2 | Assemble | `/assemble <slug>` | ~$1 |
| 3 | Verify | `scripts/verify.py`, `omissions.py`, `digest_check.py` | free |
| — | Triage | `scripts/triage.py --backend anthropic` | ~$1.20 |
| 4 | Review | `/adversary <slug> [--revise]` | ~$2.50/round |
| 5 | Measure | `scripts/mutate.py` → review → `scripts/score.py` | ~$3 |
| 6 | Contents | `scripts/contents.py` — markdown navigation, idempotent | free |
| 7 | Render | `scripts/render.py` — A4 PDF, contents, page numbers, index | free |

A full cycle on a 400-page book is roughly **$10–15**. The deterministic stages are free and
do a surprising amount of the work: `verify.py` and `omissions.py` between them cover invented
citations, fabricated quotes, untraceable numbers, uncited chapters and dropped table rows.

## The idea worth understanding

**Code does bookkeeping; the model does judgment.** Every check that can be a script is a
script, so the expensive reviewer spends its attention on the four things nothing mechanical
can reach: whether a claim is *backwards*, whether something load-bearing is *missing*,
whether synthesis is *unmarked*, and whether the result is *usable*.

Three structural decisions follow from that:

- **Chapters are read in isolated subagents.** A chapter read in the main conversation stays
  in context and is re-sent every turn. Read in a subagent, it is paid for once.
- **The reviewer cannot edit what it judges.** `adversary` has no `Edit` tool. Not a policy it
  might drift from.
- **Prompts live in files, not in agents.** Both drivers load the same `prompts/*.md`, so they
  cannot diverge.

## Layout

```
prompts/       distill · assemble · review · revise   ← the actual instructions
spec/          digest-format · summary-format         ← the output contracts
rubric/        summary-rubric                          ← severities, worked examples
scripts/       verify · omissions · digest_check · triage · mutate · score
               outline · figures · render · run · withkey
.claude/       agents/ · commands/ · skills/ · settings.json
work/<slug>/   digests, pages, figures, reviews, mutants   (gitignored, regenerable)
```

Data never lives here. Books are in `~/reference/books/<slug>/`, summaries in
`~/reference/books/summaries/`. That corpus is deliberately outside every git repo.

## Known issues

Read this before trusting any output.

**`verify.py` reports 2 Criticals on `sip-johnston` that are not real.** Typographic quotes
nested inside a quotation, and a soft-hyphen page break splitting another. The adversary
dismissed both independently across two rounds. The quote checker needs to normalise those two
cases; until then, a Critical from `quote.not_found` deserves a look before it is believed.

**`omissions.py` attributes tables by proximity, and proximity is not ownership.** Writing
"Table 4.2" in prose within five lines of a different table makes it report that table as
reproduced. A reviser hit this and worked around it by writing "Tables 4.2 and 4.8" — a
summary should not have to phrase itself around a checker. Its `absent_tables` count is also
raw: it does not know which omissions the summary *declared*, so on this book it reports 43
absent when only a handful are genuine silent losses.

**Triage's `contradicted` verdict is retired, not merely deprioritised.** Precision measured
22% → 17% → 2.6% across three rounds; two rounds of prompt tightening did not arrest it. The
failures all share one shape — a bounded per-claim check reading one window and treating a
page break as disagreement. `absent` and `incomplete` held up and are what the layer is for.

**The severity ranking is arguably backwards.** A fabrication has a second line of defence in
`verify.py`; a silent omission has none, and the reader cannot notice an absence. Yet the
rubric grades dropped detail as Major and fabrication as Critical, so round 2 shipped with
three missing tables. `PLAN.md` §6c proposes the fix; it is not yet applied.

**`run.py` produces thinner digests than the Claude Code agents.** At `--effort xhigh` it
reaches parity on claims (102 vs 105) but still trails on identifiers (89 vs 100). One-shot
generation compresses. Splitting distill into two calls — content, then the identifier ledger
— is the untried fix.

**The length budget for technical books is drawn from one book.** `TECHNICAL_BUDGET` is
15–25%, deliberately wide, provisional. Every run records its own share in `verify.json`;
revisit once three or four technical books have been through.

**Agent and command definitions load at Claude Code startup.** Editing `.claude/agents/` or
`.claude/commands/` needs a restart; `prompts/*.md` and the scripts are read at run time and
are live immediately.

**Transcribed figures are exempt from the identifier and numeral checks — by design, not an
oversight.** `verify.py`'s `check_content` skips those two for any block whose text *or heading
path* contains `TRANSCRIBED`. A ladder diagram's addresses and message numbers were read off a
page image and exist nowhere in the extracted text, so the checks could only ever produce false
positives. Quote and verbatim checks stay active. Restoring ch16's five flows added 88 message
rows and produced **zero** new findings because of this; delete the guard and it becomes
dozens.

## What to read next

| You want | Read |
|---|---|
| Why it is built this way, and what each phase found | `PLAN.md` |
| How to set it up, and what every config file does | `SETUP.md` |
| The operating procedure | `.claude/skills/book-distill/SKILL.md` |
| The rules that must not be violated | `CLAUDE.md` |

`PLAN.md` §6b and §6c are the most useful pages in the repo for anyone picking this up: they
record what was measured rather than what was intended, including three occasions where a
confident claim turned out to be wrong and how it was caught.

## Open work

- The Media Security chapter (4th edition, scanned from print) needs an image-only ingest
  path — a scan has no text layer, so `pdftotext` yields nothing.
- `mutate.py` and `score.py` have measured the adversary once. One seed is not a measurement;
  the per-class recall table needs more runs before it means anything.
- `score.py`'s finding-splitter counts report *sections*, not findings, so its precision
  column is meaningless. Recall is sound.
