# Revise a summary against a review

You are applying findings, not rewriting. The summary was expensive to build and is mostly
right; your job is to change the specific things a reviewer proved wrong, and to leave a record
of what you refused and why.

## Inputs

- `work/<slug>/review-r<N>.md` — the findings.
- `~/reference/books/summaries/<slug>.md` and `<slug>-brief.md` — what you edit.
- `work/<slug>/digests/*.md` and the chapter text — for checking a finding before applying it.

Edit in place, surgically. Do not rewrite whole sections to accommodate one corrected clause.

## Apply Critical and Major. Judge, do not obey.

**A reviewer is not an oracle.** It works from the same source you do and can be wrong — this
project has already produced a confirmed-looking finding that was false, asserted from one
paragraph while the qualifying paragraph sat nine lines above on the same page.

So for each finding: check it against the cited pages yourself before applying it. If it holds,
fix the claim. If it does not, **reject it and record why** in the revision log. A silently
ignored finding is worse than a wrong one, because the next round cannot tell the difference
between "considered and rejected" and "missed".

Minor findings: apply if cheap and safe, skip otherwise, and say which.

## How to fix things

**A reversed claim** gets corrected to what the page says, keeping the locator. If the book
states the rule in two places with different scope, say both — that is a contradiction for §11,
not a choice between them.

**A dropped detail** gets restored from the digest, with its locator. Not paraphrased back in
— restored.

**Unmarked synthesis** gets marked, not deleted. It is usually the most useful writing in the
file; the defect is the missing label.

**A stripped hedge** gets its qualifier back in the book's own words.

## What you may not do

**Never fix a finding by deleting the claim.** If a number cannot be traced to its cited page,
that is either a wrong locator or a wrong number, and both are answered by opening the digest —
not by removing the sentence. Deletion converts a visible defect into an invisible one, which
is the exact failure this pipeline exists to prevent.

Do not improve prose you were not asked about. Do not reorganise. Do not add material the
review did not ask for. Every edit should trace to a numbered finding or a rejection note.

## Output

Edit the two summary files, then write `work/<slug>/revision-r<N>.md`:

- **Applied** — finding id, what changed, and the locator you verified it against.
- **Rejected** — finding id, and the evidence that the finding was wrong. Quote the page.
- **Deferred** — anything needing the physical book or a human decision.

Report the counts and the summary's word count before and after. If it got materially shorter,
say so explicitly and explain where the words went — that is the signature of fixing findings
by deletion, and it is the thing to catch.
