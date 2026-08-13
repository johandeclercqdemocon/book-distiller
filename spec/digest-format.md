# Digest format spec

A digest is the output of reading **one part** of a book. One file per part, at
`work/<slug>/digests/<label>.md`. Digests are intermediates: regenerable, gitignored, and never
shipped.

## What a digest is for

It is a **claim ledger**, not prose, and it is deliberately over-inclusive — roughly 15–20% of the
part's words. Pruning is the assembly stage's job, because only at assembly is the whole book
visible and only then can you tell what is load-bearing. A detail dropped here is gone for good; a
detail kept here costs a few hundred tokens.

It also exists so the adversary can grade **omission**. Comparing the summary against the digests
is how "what did this leave out that I needed?" becomes an answerable question instead of a
rhetorical one.

## Shape

```markdown
# ch03 — Spectrum of LLM Adaptation: RAG to Fine-tuning
Source: text/ch03.txt · printed pp.57-94 · 24,180 words · read <date>

## Claims

- **CLAIM:** RAG and fine-tuning are complements, not alternatives; the book's decision axis is
  whether the knowledge changes faster than you can retrain. [p.61]
- **CLAIM:** Their retrieval evaluation uses recall@10 on a 4,000-question internal set. [p.73]
  - **NUMBERS:** recall@10, 4,000 questions
- **CLAIM:** ...

## Verbatim

```yaml [p.78]
retriever:
  top_k: 10
  rerank: true
```

## Tables

### Table 3.2 — adaptation techniques compared [p.81]

| Technique | Data needed | Latency cost | When |
|---|---|---|---|
| ... reproduced cell for cell ... |

## Identifiers

| Identifier | Kind | Definition | Locator |
|---|---|---|---|
| `top_k` | config key | number of chunks retrieved before rerank | [p.78] |

## Figures

- **Figure 3.4** [p.79] — retrieval pipeline. TRANSCRIBED: query → embed → ANN search (top 50) →
  cross-encoder rerank → top 10 → prompt assembly.
- **Figure 3.7** [p.88] — GAP: image not extractable from text, page not rendered.

## Author's hedges

- p.84: "in our deployments" — the latency figures are from their own infrastructure, not a
  published benchmark.

## Open questions for assembly

- ch03 and ch07 give different numbers for the same benchmark (p.73 vs p.190). Resolve or report
  both.
```

## Rules

1. **Every entry carries a page locator.** Printed pages. A claim without one cannot be used
   downstream — assembly has nothing to cite.
2. **Verbatim classes are copied, not summarised.** See `spec/summary-format.md` §2.
3. **Tables are reproduced cell for cell**, including the caption and number.
4. **Figures are inventoried, always.** `pdftotext` drops image-based figures silently, and in a
   protocol book the ladder diagrams often *are* the chapter. Every figure caption found in the text
   gets an entry: either a transcription (from the rendered page image) or an explicit `GAP:` line.
   Never omit a figure by not mentioning it.
5. **Hedges are recorded separately** so assembly cannot lose them by accident.
6. **Contradictions are surfaced, not resolved.** The digest reads one part and cannot know what
   the other parts say. Flag it and let assembly decide.
7. **No synthesis.** The digest records what the part says. Interpretation happens at assembly,
   where it gets fenced.
