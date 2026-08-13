# Distill one part of a book

You are reading **one chapter** and producing a claim ledger for it. Another pass will
assemble the book's summary from your ledger and its siblings; a third will attack that
summary. You are the only stage that reads this chapter's actual text, so anything you drop
is gone for the rest of the pipeline.

Read `spec/digest-format.md` for the output shape. This file is the job.

## Inputs

You get the chapter twice, in two forms, and they are good at different things.

- `~/reference/books/<slug>/text/<label>.txt` — extracted text. **Character-exact.** This is
  the authority for anything you copy verbatim.
- `work/<slug>/pages/<label>/p-*.png` — one image per page, in order. **Layout-exact.** This
  is the authority for structure: where a message begins and ends, what a table's columns
  really are, and every diagram, none of which survive text extraction.
- `~/reference/books/<slug>/meta.json` — the part's title, printed page range, and its
  `scope` note, which tells you what this particular chapter is for. Follow it.

Read the text first, then the pages. Both, always — not one or the other.

**Precedence.** For characters — header values, branch parameters, ports, code — the text
wins; do not retype a wire value from an image when the text has it exactly. For structure —
message boundaries, table shape, figures, anything visual — the image wins. Where the two
genuinely disagree, the image is usually right about *what is there* and the text about *how
it is spelled*; record the discrepancy in Open questions rather than quietly picking one.

Extraction damage is real and worth watching for: this corpus has already produced a page
where one SIP message was folded inside another. If a passage in the text looks structurally
wrong, look at the page image and trust your eyes.

Write to `work/<slug>/digests/<label>.md`. Nothing else.

## Be over-inclusive

You are not summarising — you are transcribing what matters into a structured form, and
"what matters" is judged generously. Assembly sees the whole book and can prune; you cannot
know what a later chapter will make load-bearing. A detail kept costs a few hundred tokens.
A detail dropped is unrecoverable.

**The budget is 15–20% of the chapter, counting prose-derived claims only.** Verbatim
blocks, reproduced tables and figure transcriptions do not count against it and are not
capped — they are copies, not compression, and there is no such thing as copying 20% of a
wire format. On a chapter that is largely message listings the digest can legitimately come
out longer than the chapter itself; that is the format working, not a failure. What the
budget governs is how hard you compress the *reasoning* around those artifacts, and under
15% there means you have thinned the explanation too far.

If you find yourself writing "various", "several", "a number of", or "different types of" —
stop and enumerate them instead.

## Page locators

Every entry carries a printed page number. Derive them from the text itself: `pdftotext`
preserves page furniture, so a page boundary looks like a bare folio on its own line, or a
running header pairing the folio with the book or chapter title:

```
                                       133
134              SIP: Understanding the Session Initiation Protocol
```

Track the current page as you read and attach `[p.134]` to each entry. If the extraction has
mangled the folios in some stretch, use the nearest one you are sure of and say so — a
locator that is approximately right is useful; an invented one is not.

## What to capture

**Claims.** Every assertion the chapter makes, in your own words, one per bullet. Direction
and polarity matter more than anything: "X overrides Y", "A is inserted only by B", "this is
hop-by-hop, not end-to-end". Getting a rule backwards is the single worst defect this
pipeline can ship, and it starts here.

**Verbatim classes — copy exactly, never paraphrase.** Protocol messages, header field
syntax, code, ABNF and other grammars, command syntax, status codes, timer values, and
error strings. Character for character, including capitalisation and punctuation:

```
INVITE sip:bob@biloxi.com SIP/2.0
Via: SIP/2.0/UDP pc33.atlanta.com;branch=z9hG4bK776asdhds
Max-Forwards: 70
```

A paraphrased wire format is not a summary of a fact, it is a different fact.

**Tables — reproduce cell for cell**, including the caption and its number. Tables survive
extraction, so there is no excuse for flattening one into prose; the comparison the table
makes *is* the content. Watch for tables split across a page break and rejoin them.

**Identifiers.** Build the ledger as you go: every header field, method, status code, RFC
number, parameter, timer, state and flag, with a one-line definition and its locator. On a
protocol book this is the highest-value thing you produce.

**Figures — transcribe every one from its page image.** Figure bodies never survive text
extraction, so in the text you see only a caption and a prose reference. **You have the page
images. Use them.** Open the page the caption sits on and read the diagram.

Transcribe into the form a reader actually wants:

| Kind | Becomes |
|---|---|
| Call-flow ladder | an ordered message list — step number, from → to, method or response code, and the headers the prose calls out |
| State machine | a transition table — state, event, next state, action |
| Architecture or topology | the components, with the links between them |
| Plot | axes with units, the series, the trend, and any labelled values |

Name the participants exactly as the diagram labels them, addresses included. A ladder
reconstructed from the surrounding prose instead of read off the diagram is not a
transcription — the diagram carries ordering, concurrency and endpoints the prose does not.

Mark each one `TRANSCRIBED [p.N]`, because a transcription is inference from an image and a
later stage must be able to tell it from copied text. Write `GAP:` **only** when there is
genuinely no image for that page, and say why. Never let a figure pass unmentioned.

**The author's hedges.** "In our experience", "this may change", "most implementations" —
record these separately. A summary that drops the qualifier is more confident than the book,
which is a fabrication of certainty.

**Contradictions and open questions.** You read one chapter and cannot know what the others
say. If a figure disagrees with the prose, or a value here conflicts with one you were told
elsewhere, flag it for assembly. Do not resolve it.

## What not to do

- **No synthesis.** Record what the chapter says. Interpretation happens at assembly, where
  it gets fenced as yours. If you catch yourself writing "this suggests" or "in practice this
  means", you have crossed the line.
- **No editorialising about quality.** Whether the chapter is well-written is not information.
- **No skipping the boring parts.** Reference lists, exact field orderings and boilerplate
  are exactly what someone will come back for.
- **No smoothing over confusion.** If a passage is genuinely unclear, record it as unclear
  with the locator, rather than picking the reading that sounds tidiest.

## Dated material

Some chapters describe a landscape that has moved since publication. Record what the book
says as what the book says, and add a `DATED:` note where a claim is clearly time-bound
(market predictions, "currently under development", version numbers). Do not correct the
book from your own knowledge — that is the assembly stage's business, fenced as synthesis,
and a correction smuggled in here is indistinguishable from the source.

## Finishing

**Do not count your own output.** `scripts/digest_check.py` measures every digest against its
source chapter — word counts, compression share, claims, locator coverage, identifiers, and
figures accounted for against the render inventory. It is exact and you are not: earlier runs
reported a 4,464-word chapter as "~6,400" and a 9,987-word digest as "~3,050", and spent
attention on arithmetic that a script does for free.

So end with substance, not statistics — the things a script cannot see:

- **Contradictions you found** between figure and text, prose and wire, or one part of the
  chapter and another. Say what disagrees and where; do not resolve it.
- **Damage you had to work around** — a page where extraction folded one message into
  another, a glyph the image could not settle, a stray running head printed inside a block.
  Distinguish a defect printed in the book from an artifact of extraction, because assembly
  and the reviewer will treat them differently.
- **Anything you could not read**, and why.
- **What the next stage would get wrong** without something you know from having read this
  chapter closely.

If nothing surprised you, say so plainly rather than padding the section.
