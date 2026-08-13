---
description: Distil one or more parts of a book into claim ledgers
argument-hint: <slug> [label ...] | <slug> --all
allowed-tools: Read, Glob, Bash(uv run:*), Task
---

Distil book `$1`.

If further arguments name parts, distil exactly those. If the only other argument is
`--all`, distil every part in `~/reference/books/$1/meta.json` that has extracted text and
does not already have a digest in `work/$1/digests/`. With no further arguments, list the
book's parts, which already have digests, and their word counts — then stop and ask which
to run.

**Before dispatching anything, check the page images exist** for every part you are about to
run — `work/$1/pages/<label>/` should hold one PNG per page of that chapter. If any are
missing, render them first:

```
uv run python scripts/figures.py $1 --pages
```

A distiller run without page images silently degrades into a text-only pass that reports
every diagram as a gap, so this check is not optional.

Delegate each part to the **distiller** subagent, one invocation per part, sending
independent parts in a single message so they run concurrently. Tell each one its slug, its
part label, and the path to its page-image directory. Never distil a part in this
conversation directly: the whole point is that each chapter is read in its own context and
does not accumulate here.

Before dispatching, state how many parts will run and roughly what that will cost — a part
costs about its own token count in input, plus its page images at ~1,600 tokens each, plus
about a fifth of that in output.

When they return, do not repeat their self-reported counts. Run:

```
uv run python scripts/digest_check.py $1
```

and report that table instead — it is exact, and the subagents' own arithmetic has been
wrong in both directions. Flag any part it marks with a problem, and surface the
contradictions and extraction damage the subagents reported, which is the part a script
cannot see.
