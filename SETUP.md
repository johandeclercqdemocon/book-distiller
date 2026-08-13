# Setting this project up from a console

Two things in one document: **how to build this repo from nothing**, and **what every
configuration file does and why it says what it says**. Part 3 is the reference — read it
when you want to know why a file exists, not just what to type.

Claude Code's configuration surface moves between releases. Where a detail is load-bearing,
check it against [code.claude.com/docs](https://code.claude.com/docs) rather than trusting
this file or any book about it.

---

## Part 1 — prerequisites

```bash
uv --version && pdftotext -v && pdftoppm -v
```

| Tool | Why | If missing |
|---|---|---|
| `uv` | every Python entry point | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `pdftotext`, `pdftoppm`, `pdfinfo` | text extraction, page rendering, page counts | `sudo apt install poppler-utils` |
| pango + harfbuzz | WeasyPrint's text layout for the A4 PDF | present on Ubuntu 24.04; `sudo apt install libpango-1.0-0` otherwise |
| `calibre` | EPUB only — not needed while the corpus is all PDF | `sudo apt install calibre` |

Python packages (`pypdf`, `weasyprint`, `markdown`) are **not** installed by hand. They live in
`pyproject.toml` and `uv` fetches them on first `uv run`.

---

## Part 2 — building the repo from zero

### 1. Directory and git

```bash
mkdir -p ~/claude/book-distiller && cd ~/claude/book-distiller && git init
```

The corpus at `~/reference/books` stays **outside** this repo — purchased material, older than
this project, and `~/reference/.gitignore` contains `*` as a guard. This repo holds code and
prompts only.

### 2. Skeleton

```bash
mkdir -p .claude/agents .claude/commands .claude/skills scripts spec rubric prompts print evals work
```

### 3. Python project

```bash
uv init --bare 2>/dev/null; uv add pypdf weasyprint markdown
```

`uv add` writes the dependency into `pyproject.toml` and resolves `uv.lock`. Set
`package = false` under `[tool.uv]` afterwards — this is a bag of scripts, not an installable
library, and without that flag `uv` will try to build it.

### 4. The files

Write these in this order; each is explained in Part 3.

| File | Purpose |
|---|---|
| `CLAUDE.md` | rules Claude Code loads into every session here |
| `.claude/settings.json` | permissions and corpus access, shared and committed |
| `.gitignore` | keeps intermediates and any stray PDF out of git |
| `spec/summary-format.md` | the output contract — locators, verbatim classes, required sections |
| `spec/digest-format.md` | the per-chapter intermediate format |
| `rubric/summary-rubric.md` | how the adversary scores, with worked examples |
| `print/a4.css` | the A4 print stylesheet |
| `scripts/corpus.py` | read-only loader for the book corpus |
| `scripts/verify.py` | deterministic checks on a finished summary |
| `scripts/outline.py` | drafts `meta.json` from a PDF's bookmarks |
| `scripts/render.py` | markdown → A4 PDF with contents, page numbers and an index |

### 5. Check it works

```bash
uv run python scripts/verify.py agentic-coding-claude-marco --max 5
```

This runs against the summary that already exists in the corpus and should report real findings.
If it prints a book title and a findings list, the wiring is correct.

---

## Part 3 — the configuration files explained

### 3.1 `CLAUDE.md` — the always-loaded instructions

**What it is.** Claude Code reads `CLAUDE.md` from the project root at session start and keeps it
in context for the whole session. It is the one file guaranteed to be read, so it holds the rules
that must never be violated, and nothing else.

**How it is found.** Several layers load together, and they add up rather than replace:

| Layer | Path | Scope |
|---|---|---|
| User | `~/.claude/CLAUDE.md` | every project you open |
| Project | `./CLAUDE.md` | this repo, committed and shared |
| Subdirectory | `sub/dir/CLAUDE.md` | pulled in when files there come into play |
| Import | `@path/to/file.md` inside any of the above | inlines another file |

**What ours says, and why.** Seven rules, each of which exists because breaking it silently
destroys the product: locators mandatory; verbatim classes copied not paraphrased; synthesis
fenced; omission declared; hedges preserved; the corpus `STATUS: untested` rule; outputs stay
local. Plus where data lives, and `uv` only.

**What it must not become.** A place for background reading, architecture essays, or anything
already in `PLAN.md`. Every token here is paid on every request in the session. If it is not a
rule you would enforce in review, it belongs in `spec/`, `PLAN.md`, or a skill that loads on
demand.

### 3.2 `.claude/settings.json` — permissions, committed

**What it is.** Project settings, meant to be checked into git and shared. Ours does three things.

**`permissions.allow`** — patterns that run without a prompt. The syntax is `Tool(pattern)`, where
Bash patterns match a command prefix:

```json
"Bash(uv run:*)"        // any `uv run …`
"Read(/~/reference/books/**)"
```

Note `//` at the start of an absolute path in `Read`/`Write` patterns — a single leading slash is
read as relative to the project. (Your `~/.claude/settings.json` uses the older `Bash(uv run *)`
space form; both appear in the wild, the colon form is the documented one.)

**`permissions.deny`** — a hard no, outranking any allow. Ours forbids writing to
`<book>/source/**` and `<book>/text/**`: the extracted text is evidence, and a model that can
"fix" its evidence can make any finding go away. It also blocks edits to the downstream project
`EMPIRICAL_FINDINGS.md`, whose whole authority comes from being derived only from real call
transcripts.

**`permissions.additionalDirectories`** — the corpus is outside this project, so without listing
it here every read of a book would prompt. Adding a directory here grants read access for the
session; it does not make the `deny` rules above go away.

**Precedence**, highest first: enterprise policy → command-line flags →
`.claude/settings.local.json` → `.claude/settings.json` → `~/.claude/settings.json`. So a personal
override in `settings.local.json` beats the committed project file, which beats your global one.

**`.claude/settings.local.json`** is the same shape but gitignored — machine-specific paths and
one-off grants. Claude Code writes to it when you approve something permanently. It is in
`.gitignore` for a reason: it accumulates absolute paths and personal allowances that mean nothing
on another machine.

**Hooks** also live in settings, and are the one mechanism that is *deterministic* — they are shell
commands the harness runs on events (`PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`,
`SessionStart`, and others), not instructions the model may forget. We do not use one yet. The
obvious candidate later is a `PostToolUse` hook running `verify.py` whenever a summary file is
written, so a broken citation is caught the moment it is introduced rather than at review time.
Deferred until the write path exists.

### 3.3 `.claude/agents/*.md` — subagents

**What it is.** One markdown file per subagent. Each runs in **its own context window** and returns
only its final message to the main session.

**Shape:**

```markdown
---
name: adversary
description: Adversarial reviewer. Use after a summary is assembled and verify.py is clean.
tools: Read, Grep, Glob
model: opus
---

The system prompt for this agent goes here.
```

| Field | Effect |
|---|---|
| `name` | how you invoke it |
| `description` | what the main session uses to decide when to delegate — write it as *when to use this*, not what it is |
| `tools` | omit to inherit everything; list to restrict |
| `model` | which model runs it |

**Why this matters here.** Two independent reasons, and both are the point of the design:

1. *Isolation.* The adversary must not share context with whatever wrote the summary. A reviewer
   that watched the summary being written grades its own reasoning and finds it sound.
2. *Least tools.* `tools: Read, Grep, Glob` makes the adversary structurally incapable of editing
   the thing it is judging. Not a policy it might drift from — a capability it does not have.

Three are planned: `distiller` (phase 2), `adversary` and `reviser` (phase 4). None exist yet.

### 3.4 `.claude/commands/*.md` — slash commands

**What it is.** A file called `distill.md` becomes `/distill`. The body is a prompt template.

```markdown
---
description: Distill one book part into a digest
argument-hint: <slug> <part-label>
allowed-tools: Read, Write, Bash(uv run:*)
---

Read @spec/digest-format.md, then distil part $2 of book $1.
```

`$ARGUMENTS` is everything after the command; `$1`, `$2` are positional. `@path` inlines a file at
run time. Subdirectories namespace the command (`.claude/commands/book/distill.md` → `/book:distill`).

The distinction from a skill: a command is **you** invoking a fixed procedure; a skill is
**Claude** deciding to load knowledge because the task calls for it.

### 3.5 `.claude/skills/<name>/SKILL.md` — loaded on demand

```markdown
---
name: book-distill
description: How to distil, assemble, verify and review a book. Use when working on a summary in this repo.
---

Body: the procedure, kept short, linking to references/ for detail.
```

The value is **progressive disclosure**: only the `name` and `description` sit in context all the
time. The body loads when Claude judges the skill relevant, and files under `references/` load only
when the body sends it there. That is what lets the rubric and the format spec be long without
costing anything on unrelated turns.

Which is also why `spec/` and `rubric/` are separate files rather than sections of `CLAUDE.md`:
`CLAUDE.md` is paid always, a skill reference is paid when used.

### 3.6 Choosing between the four

| Primitive | Chooses to load it | Own context | Use for |
|---|---|---|---|
| `CLAUDE.md` | always loaded | no | invariant rules |
| Skill | Claude, by relevance | no | procedures and reference material |
| Slash command | you, explicitly | no | a fixed step you run by hand |
| Subagent | Claude or you | **yes** | work needing isolation or a big read |

The adversary is a subagent *because of* the third column. Nothing else gives it a fresh context.

### 3.7 `pyproject.toml` and `uv`

Declares the three dependencies, `requires-python`, `package = false` (scripts, not a library), and
a `[tool.pyright]` block pointing the type checker at `scripts/` and `.venv` so cross-imports and
third-party packages resolve.

Run everything as `uv run python scripts/<name>.py`. `uv` creates `.venv`, installs what is missing,
and pins versions in `uv.lock`. Never `pip install`, never a hand-made venv — a script that works
for you and not in a fresh clone is a bug that surfaces months later.

### 3.8 `.gitignore`

`work/` (regenerable intermediates), `*.pdf` and `*.epub` (a guard: no corpus material should ever
land in this repo, and a stray `git add .` is how it would), `.claude/settings.local.json`, and the
usual Python noise.

### 3.9 `print/a4.css`

Not Claude configuration — the print stylesheet, and the reason the PDF has real page numbers.
WeasyPrint implements CSS Paged Media, so:

- `@page { size: A4 }` with margin boxes for the running header and the page number
- `string-set` on `h2` puts the current section name in the header
- `leader('.') target-counter(attr(href), page)` fills in contents page numbers **at layout time**
- the same `target-counter` gives the back-of-book index its page references
- `bookmark-level` on headings produces the PDF outline

Nothing here is written by hand or by a model, so nothing can drift from the text.

---

## Part 4 — what you can run today

Draft a manifest from a PDF's bookmarks (prints to stdout; `--write` to save, with a backup):

```bash
uv run python scripts/outline.py <slug>
```

Check a finished summary — exits non-zero if anything Critical or Major survives:

```bash
uv run python scripts/verify.py <slug> --max 0
```

Render the A4 print edition next to the markdown:

```bash
uv run python scripts/render.py <slug>
```

`verify.py` also writes `work/<slug>/verify.json`, which is what the adversary will read in phase 4
so it does not waste attention on things a script already checked.

## Part 5 — what does not exist yet

`prompts/`, `.claude/agents/`, `.claude/commands/` and `.claude/skills/` are empty. They are phases
2–5 in `PLAN.md`: the distiller, the assembly step, the adversary and revise loop, and the mutation
eval that measures whether the adversary actually catches injected defects.

Everything built so far is deterministic and bills no inference. From phase 2 onward, runs cost
model tokens — order of 0.5–1M input tokens for a full cycle on a 350-page book.
