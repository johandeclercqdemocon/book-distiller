---
version: 1
applies_to: summaries/<slug>.md and <slug>-brief.md
---

# Summary rubric

Used by the adversary reviewer to score, and by the reviser to prioritise. Every dimension is
scored 0–4 with the **worst defect present** setting the ceiling, not the average impression.

The worked examples below are real. They come from the twelve discrepancies found when
`summaries/agentic-coding-claude-marco.md` was adversarially reviewed on 2026-08-06. Abstract
criteria produce abstract findings; a grader needs to have seen the actual shape of the error.

## Severity

| | Definition | Gate |
|---|---|---|
| **Critical** | A false statement, a reversed rule, an invented citation, a fabricated quote, or a wrong identifier in a technical book. The reader will act on it and be wrong. | Blocks. Zero Criticals required to ship. |
| **Major** | Load-bearing detail dropped, a part uncovered, synthesis passed off as the book's, a hedge stripped. | Fixed unless explicitly rejected with a reason. |
| **Minor** | Imprecision, structure, style, navigation. | Fixed if cheap. |

**Every finding must quote the summary line and the source line, each with a locator. A finding
without evidence is dropped, not softened.** An unconstrained critic invents objections exactly as
readily as an unconstrained author invents claims, and a plausible false finding costs a revision
round and can inject an error into a correct summary.

---

## 1. Fidelity — does it say what the book says?

| Score | Meaning |
|---|---|
| 4 | Every sampled claim checks out against its cited text. |
| 3 | Minor imprecision only; nothing a reader would act on wrongly. |
| 2 | One or more claims overstate or blur what the source supports. |
| 1 | A claim is materially wrong. |
| 0 | A rule is stated backwards, or a citation points at text that does not contain the claim. |

**Worked example — reversed rule (Critical).** The Marco summary's §1 stated the `memory/` directory
placement rule the wrong way round. It read fluently, it was specific, it cited the right chapter,
and it was exactly inverted. This is the highest-value defect class to hunt: *plausible, specific,
and backwards*. Check direction and polarity on every rule of the form "X goes in Y", "A overrides
B", "higher wins".

**Worked example — solved-problem inflation (Critical).** §4a claimed the book fixes the
subagent-output problem. The book raises it and does not fix it. Any sentence of the form "the book
solves/provides/handles X" needs the source checked for whether it actually delivers or merely
names the problem.

## 2. Retention — did the nitty-gritty survive?

Scored against the **digests**, not against impressions. This is the dimension the whole project
exists for: a fluent summary that dropped the numbers has failed at its only job.

| Score | Meaning |
|---|---|
| 4 | Every figure, table cell, threshold, identifier and exact syntax in the digests is either present or explicitly declared as compressed. |
| 3 | Trivial losses only. |
| 2 | A quantitative claim survives without its number, or a table was flattened into prose. |
| 1 | A load-bearing table, figure or identifier set is missing. |
| 0 | The summary is qualitative where the source was quantitative. |

Hunt for: "significantly", "much faster", "several", "a number of" — each is usually a deleted
number. And for tables that became sentences.

**Technical books** (`technical: true` in `meta.json`): a wrong identifier, status code, header name,
RFC number or timer value is **Critical**, not Minor. In a protocol reference a plausible wrong
constant is worse than an omission — an omission sends you to the book, a wrong constant sends you
to production.

## 3. Coverage — is the whole book represented?

| Score | Meaning |
|---|---|
| 4 | Every part cited, weighted roughly by content, and thin coverage is declared with a reason. |
| 3 | One part underweight relative to its content. |
| 2 | A part is present in name only. |
| 1 | A part is uncited. |
| 0 | A part is missing from the chapter index entirely. |

**Worked example — the vanished chapter (Critical).** Chapter 5 of the Marco book was absent from
the summary altogether. Nothing in the text signalled the absence; it was found only by walking
`meta.json` part by part. This is why the chapter→topic index is mandatory and why `verify.py`
counts citations per part — the eye does not notice what is not there.

## 4. Honesty — can the reader tell what is what?

| Score | Meaning |
|---|---|
| 4 | Synthesis fenced, hedges preserved, gaps stated, dating risk flagged, the book's own caveats about its authority carried over. |
| 3 | Fencing present but inconsistently applied. |
| 2 | A hedge was stripped, making the summary more confident than the book. |
| 1 | Synthesis reads as the book's position. |
| 0 | Unfenced synthesis contradicts the book. |

**Worked example — unfenced synthesis (Major).** The Marco summary's §7, a comparison the book never
makes, originally read as the book's argument. The fix was not to delete it — it is the most useful
section in the file — but to fence it. Useful synthesis is welcome; unlabelled synthesis is not.

**Worked example — the author's own caveat.** That book states its account of Claude Code internals
comes from public blog posts, not Anthropic. A summary that drops that qualifier manufactures
authority the source never claimed. Look for the source's epistemic status and check it travelled.

## 5. Usability — can you find and trust a thing quickly?

| Score | Meaning |
|---|---|
| 4 | Organised by task, navigable, any claim traceable to source in under a minute. |
| 3 | Good structure, some hunting required. |
| 2 | Organised by chapter — the author's order, not the reader's need. |
| 1 | Requires reading start to finish to find anything. |
| 0 | Claims cannot be traced back at all. |

---

## Scoring output

The reviewer reports, per artifact: a score per dimension with a one-line justification, the full
findings list ordered by severity, and an explicit **ship / do not ship** verdict driven only by the
Critical count. Scores inform; the Critical gate decides.

## What the reviewer must not do

- Do not reward length, polish, or confident tone. All three correlate negatively with fidelity.
- Do not raise a finding you cannot evidence with a source quote and locator.
- Do not propose rewrites for style. Report the defect; revision is a different pass with a
  different job.
- Do not assume the summary is wrong when it disagrees with your recollection of the field. The
  question is only ever whether it matches **this book**.
