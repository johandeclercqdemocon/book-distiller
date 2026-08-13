---
description: Adversarially review a book summary, and optionally revise against the findings. Named /adversary, not /review, to avoid colliding with the built-in GitHub PR reviewer.
argument-hint: <slug> [--revise]
allowed-tools: Read, Glob, Bash(uv run:*), Task
---

Review the summary for book `$1`.

**Run the free checks first** — they are deterministic, cost nothing, and every finding they
produce is one the reviewer does not have to spend attention on:

```
uv run python scripts/verify.py $1 --max 0
uv run python scripts/omissions.py $1
```

If `work/$1/triage-*.json` is missing, say so and ask before running triage — that one bills
the API. Without it the reviewer loses per-claim coverage but can still work.

Then delegate to the **adversary** subagent with the slug and the round number (r1 unless
earlier rounds exist in `work/$1/`). Never review in this conversation: the reviewer must not
share context with whatever wrote or last edited the summary, which is the whole reason it is
a subagent with read-only tools.

When it returns, report the verdict, the severity counts, and how many triage flags it
confirmed versus dismissed — that last number is the one worth watching, because it measures
whether the cheap layer is earning its place.

## With `--revise`

Only if the reviewer found Critical or Major findings, and only after showing them to the user
and getting a go-ahead. Then delegate to the **reviser** subagent, which applies findings and
records the ones it rejects with reasons.

After revision, re-run `verify.py` and `omissions.py`, then start round N+1 with a fresh
adversary. Stop when a round returns zero Criticals, or after three rounds — then report what
is still open rather than looping.

A revision that only deletes the sentences that triggered findings is a failure, not a fix.
Watch for it: if the summary got materially shorter, say so.
