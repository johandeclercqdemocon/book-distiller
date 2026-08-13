# book-distiller

Turns a book into a markdown distillation dense enough to replace reading it, then has an
adversarial reviewer try to break it. Plan: `PLAN.md`. Setup and config reference: `SETUP.md`.

## Where things live

Code here. Data never here.

| What | Where |
|---|---|
| Book sources, extracted text, `meta.json` | `~/reference/books/<slug>/` |
| Finished artifacts | `~/reference/books/summaries/<slug>.md` and `<slug>-brief.md` |
| Digests, verify output, reviews | `work/<slug>/` (gitignored) |
| Prompts, specs, rubric | `prompts/`, `spec/`, `rubric/` |

`~/reference/books` is deliberately outside every git repo. Never `git add` anything from it, never
propose moving it here.

## Rules that are not negotiable

1. **Locators.** Every claim-bearing block in a summary carries a locator resolving to a real part —
   `[ch07 p.142]`. Grammar in `spec/summary-format.md`. An invented citation is the worst defect
   this project can ship.
2. **Verbatim classes.** Protocol messages, code, grammars, header tables, state tables, command
   syntax and error codes are copied character-for-character, never paraphrased. A paraphrased wire
   format is a lie.
3. **Synthesis is fenced.** Anything not from the book is marked `**my construction, not the
   book's**`. No exceptions.
4. **Omission is stated, never silent.** A chapter compressed hard still gets a line saying so and
   why. Silent loss is the failure this project exists to prevent.
5. **The author's hedges survive.** If the book says its account is inferred rather than
   authoritative, the summary says so too.
6. **Corpus rule.** A book claim is a hypothesis: `STATUS: untested`. Nothing here ever graduates
   into your project's empirical-findings file, whose authority comes from real call
   transcripts. Candidates go to a candidates file.
7. **Outputs stay local.** Derived work from copyrighted sources. Do not publish or redistribute.

## How work is divided

Code does bookkeeping. The model does judgment. If a check can be written as a script, it belongs in
`scripts/`, not in a prompt — the reviewer's attention is the scarce resource and it must not be
spent counting.

## Python

`uv` only. `uv run python scripts/verify.py <slug>`. Never `pip install`, never a bare `python3` for
anything that imports a dependency, never a hand-rolled venv. Dependencies go in `pyproject.toml`.

## Prompts live in files

`prompts/*.md` are loaded by the agent definitions rather than inlined, so a later Python/API runner
uses the same text and the two drivers cannot drift. Editing a prompt means editing the file, not
the agent.
