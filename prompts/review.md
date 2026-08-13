# Attack the summary

You are trying to find what is wrong with a finished summary. Not to appreciate it, not to
improve its prose — to find claims a reader would act on and be wrong.

Read `rubric/summary-rubric.md` first: it defines the severities, the evidence rule, and the
worked examples. This file is the job.

## Your job is smaller than it looks, because scripts did the rest

Do not spend attention on anything already checked mechanically. Read these first and treat
their output as established:

| File | Already settled |
|---|---|
| `work/<slug>/verify.json` | invented citations, fabricated quotes, numerals and identifiers absent from the cited part, uncited chapters, length |
| `work/<slug>/omissions.json` | identifiers and table rows present in the digests but missing from the summary |
| `work/<slug>/triage-*.json` | every claim and ledger row read against its cited pages |

What is left is what none of them can do: whether a claim is **backwards**, whether something
load-bearing is **missing**, whether synthesis is **unmarked**, and whether the thing is
**usable**. That is your entire remit. Spend the budget there.

## Which triage verdicts to act on

`triage-*.json` used a small model to touch every claim. The file names which verdicts are
actionable, and you should honour that list rather than reading every verdict as a lead.

**Act on `absent` and `incomplete`.** These held up across two measured review rounds: "the
cited pages do not discuss this" is a judgement about citation quality that a single reading
window can reliably make, and a wrong locator is a real defect.

**Ignore `contradicted`.** It is recorded in the JSON but excluded from the actionable list
deliberately. Measured across two rounds it ran at 17–22% precision — 24 flags re-derived, 4
confirmed — and the failures shared one shape: the model treating a page break as a
disagreement. Twenty dismissals to find four confirmations is your attention spent on noise,
and you find that class better yourself, by reading whole pages.

Re-derive anything you do act on. A flag passed through without re-derivation is not a
finding, it is a forwarded rumour.

## Read the whole page before calling a contradiction

The most expensive error made on this project was asserting a scope reversal from one
paragraph. The claim was that a timer bound applied only to INVITE transactions; the paragraph
quoted said exactly that, and the paragraph nine lines above it — same page — gave the same
bound for non-INVITE transactions. The claim was right and the finding was wrong, and it went
on to corrupt the tool that found it.

**Before writing a contradiction finding:** read the full cited page, the page before, and the
page after. Search the rest of the chapter for the same term. A book states a rule in one place
and qualifies it in another, and a summary that merges both is doing its job.

## What to hunt, in order of value

**1. Unmarked synthesis.** Anything that is the summary's construction and reads as the book's.

**This is first because you are the only thing that can find it.** Reversals, wrong citations,
altered numbers and dropped table rows all have deterministic backstops — `verify.py` and
`omissions.py` catch them whether you do or not. A missing `**My construction, not the book's.**`
marker has nothing to compare against: there is no artifact on disk that records which claims
the book made and which the summary invented. If you miss it, nobody catches it, and it ships
as the author's position. It is first because of that asymmetry, not because of a measured
weakness: the one clean measurement to date put you at 1 of 1 on this class and 5 of 5 on
reversals, but a single instance measures nothing. Treat this class as unmeasured and spend
the attention anyway — a miss here is the only miss with no second line of defence.

**The specific check: every claim that joins two chapters.** A summary's most valuable
sentences connect things the author kept apart — "the NAT problem in ch10 is the same
reachability assumption ch02's rendezvous model depends on". That is good work and belongs in
the file. It is also, by construction, not something the book says. So for each one, go and
look: does the book itself make this connection, in either chapter, in a cross-reference, or
anywhere? If it does, cite it. **If it does not and the claim carries no synthesis marker,
that is a Major finding** — not because the reasoning is wrong, but because a reader cannot
tell it from a claim about the book.

Hunt them by shape. Any sentence spanning two chapters' locators. Any locator-free sentence
sitting between cited ones. Any "in practice this means", "the same failure mode", "which is
why", "taken together", "the underlying idea". Any table whose rows come from different
chapters. Any section whose organising idea has no locator at all — a framing like "everything
is either X or Y" is an editorial choice about how to present the book, and if the book does
not frame it that way, it is yours.

Check the fencing is honest, too, not just present. A marker on the paragraph after the
synthesis does not cover it, and a hedged "arguably" is not a marker.

**2. Reversal and polarity.** The defect that reads perfectly and is exactly backwards. Every
claim of the form "A overrides B", "X adds, Y removes", "must / must not", "end-to-end /
hop-by-hop", "required / optional". This class is why the project exists — the Marco summary
shipped a `memory/` placement rule stated backwards, and it survived a human read.

**3. Retention.** You have the digests: the record of what the chapters actually contained.
What did assembly drop that a reader needs? Numbers that became "several", a table flattened
into prose, a threshold gone, a hedge stripped. `omissions.json` covers ledger rows and table
rows mechanically — you cover judgment: the thing that was kept but hollowed out.

**4. Manufactured confidence.** The book hedges — "in our experience", "not commonly
implemented", "generally not SIP". A summary that drops the qualifier is more certain than its
source. Grep the digests' hedge sections and check each one arrived.

**5. Usability.** Organised by task or by the author's table of contents? Can a claim be traced
to its page in under a minute? This is the cheapest to assess and the least important — do it
last, and briefly.

## The evidence rule

**Every finding quotes the summary line and the source line, each with a locator. A finding
without both is dropped, not softened.** An unconstrained critic invents objections exactly as
readily as an unconstrained author invents claims, and a plausible false finding costs a
revision round and can inject an error into a correct summary.

For a contradiction, name both halves explicitly: what the summary says, what the page says,
and why acting on one differs from acting on the other. If you cannot write that sentence, you
do not have a contradiction — you have a paraphrase.

## What you may not do

- **Do not rewrite.** Report the defect; revision is a separate pass with a different job.
- **Do not correct the book.** If the book is wrong about SIP, that is not a summary defect.
  The only question is whether the summary says what this book says.
- **Do not reward length, polish or confident tone.** All three correlate negatively with
  fidelity.
- **Do not disagree from memory.** If the summary contradicts what you know about the field,
  check the page. The book may be dated, or wrong, and the summary faithful.
- **Do not raise style findings.** If a section is well written but false, that is one finding,
  not two.

## Coverage you must achieve

You cannot read everything. Cover, in this order, and say in the report what you covered:

1. Every flag in the triage files whose verdict appears in that file's `actionable`
   list — currently `absent` and `incomplete` — re-derived.
2. Every finding in `verify.json` that survived — the Criticals especially.
3. Every table and every numeric claim in the summary.
4. Every claim in the chapters marked `depth: full` that carries a polarity word.
5. A sample of the rest, chosen for load-bearingness, not at random.

## Output

Write `work/<slug>/review-r<N>.md`:

- **Verdict** — ship or do not ship, driven only by the Critical count.
- **Scores** — one line per rubric dimension with a one-sentence justification.
- **Findings** — ordered by severity. Each: severity, where in the summary (line and quote),
  what the source says (locator and quote), and one sentence on what a reader would get wrong.
- **Triage adjudication** — each flag you re-derived, confirmed or dismissed, with the reason.
- **Coverage** — what you read and what you did not, plainly.
- **What you could not settle** — questions needing the physical book or a human.

End with the count of findings by severity. Nothing else.
