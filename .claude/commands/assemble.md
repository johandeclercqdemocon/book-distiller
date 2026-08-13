---
description: Assemble a book's deep summary and brief from its digests
argument-hint: <slug>
allowed-tools: Read, Glob, Bash(uv run:*), Task
---

Assemble the summary for book `$1`.

**Check completeness first.** Every part marked `in_scope` in `~/reference/books/$1/meta.json`
must have a digest in `work/$1/digests/`. Run:

```
uv run python scripts/digest_check.py $1
```

If a part is missing, or a digest is flagged with a structural problem, stop and say so —
assembling from an incomplete set produces a summary with holes that nothing downstream can
detect, because the missing chapter leaves no trace.

Then delegate to the **assembler** subagent, once, with the slug. Do not assemble in this
conversation: the digests are far larger than the summary and must not accumulate here.

When it returns, report its `verify.py` result and the contradictions it resolved or left
open. Then say what remains — the adversarial review (phase 4) has not run, so the summary is
unreviewed and should be treated as a draft no matter how finished it reads.
