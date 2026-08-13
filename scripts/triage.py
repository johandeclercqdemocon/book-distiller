#!/usr/bin/env python3
"""Local-model triage: touch every claim, so the real reviewer can be selective.

    uv run python scripts/triage.py <slug> [--kind claims|ledger|both] [--limit N]

An adversary with a real budget can sample a few hundred of a summary's claims. It cannot
read all 1,276 of them against their cited pages. A small local model can — each check is one
claim against one page, a few hundred tokens, and there is no per-token cost to running it
1,276 times. That is the trade this script makes: no judgment, but total coverage.

**Triage may only raise suspicion, never clear it.** A `supported` verdict from an 8B model
is not verification, and nothing downstream may treat it as one. The output is a ranked
worklist for the adversary, so its attention goes to the flagged subset instead of a blind
sample. If this ever becomes a gate, it has quietly replaced the reviewer with a weaker model.

Needs Ollama running locally (`ollama serve`). No API key, no network, no cost.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402
import figures  # noqa: E402
import verify  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OLLAMA = "http://localhost:11434/api/generate"
DEFAULT_MODEL = {"ollama": "qwen2.5-coder:7b-instruct-q8_0", "anthropic": "claude-haiku-4-5"}
# Ordered by how much a reviewer should care. `incomplete` exists because the first run
# labelled omissions as contradictions: "the page does not mention the id parameter" is not
# the page saying the opposite, and conflating them buried three real reversals among six flags.
RANK = {
    "contradicted": 0, "absent": 1, "unclear": 2, "incomplete": 3,
    "supported": 4, "error": 5, "no-page": 6,
}
# What the reviewer is shown. `contradicted` is deliberately NOT here: across two review
# rounds it ran at 22% then 17% precision — 24 flags re-derived, 4 confirmed — and the
# failures shared one shape, the model reading a page break as a disagreement. `absent` and
# `incomplete` held up both rounds, because "this page does not discuss this" is a judgement
# about citation quality that a single window can actually make.
#
# `contradicted` is still recorded in the JSON, still ranked first, and still worth reading
# by a human tuning the prompt. It just no longer reaches the adversary as a flag, because
# twenty dismissals to find four confirmations is the reviewer's attention spent on noise.
ACTIONABLE = ("absent", "incomplete")
HINT_ONLY = ("contradicted",)

# Same contract on both backends, so verdicts stay comparable across a local/API sample.
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["supported", "incomplete", "contradicted", "absent", "unclear"],
        },
        "evidence": {"type": "string"},
        # A contradiction must name both halves of the conflict. One that cannot is a
        # paraphrase the model talked itself into, and those were a third of the last run.
        "conflict": {
            "type": "object",
            "properties": {"statement_says": {"type": "string"}, "pages_say": {"type": "string"}},
            "required": ["statement_says", "pages_say"],
            "additionalProperties": False,
        },
        "note": {"type": "string"},
    },
    "required": ["verdict", "evidence", "conflict", "note"],
    "additionalProperties": False,
}

# Headings whose whole purpose is to record disagreement between pages.
_CONTRADICTION_RE = re.compile(r"contradict|conflict|left open|printed defect", re.I)
_LEDGER_ROW_RE = re.compile(r"^\|\s*`?([^`|]+?)`?\s*\|\s*([^|]*?)\s*\|\s*(.+?)\s*\|\s*(\[[^\]]+\])\s*\|\s*$")

PROMPT = """You compare ONE statement against the pages of a book it cites. Judge only what these pages say.

PAGES ({pages} of chapter {label}):
\"\"\"
{page_text}
\"\"\"

STATEMENT:
\"\"\"
{claim}
\"\"\"

Different wording is not disagreement. "changes each time a registration is refreshed" and
"changes on every registration refresh" say the same thing. Before choosing "contradicted",
ask whether someone acting on the statement would do something DIFFERENT from someone acting
on the pages. If they would act the same, the verdict is "supported".

Choose exactly one verdict:
- "contradicted" — acting on the statement would lead someone to do the wrong thing, because
  the pages say the opposite: a reversed direction, a different number, the other party
  performing the action, or a property the pages assert and the statement denies (pages say
  a header "can be used by UAs for simple call screening", statement says it is "not used by
  the protocol"). This is the verdict that matters most.
  To use it you must fill in `conflict` below with both phrases. If you cannot quote a phrase
  from the pages that opposes a phrase in the statement, it is not a contradiction.
- "absent" — the pages do not discuss this subject at all. The citation may be wrong.
- "incomplete" — everything the pages DO say agrees, but they are silent on part of the
  statement. Normal and usually fine: a summary merges definitions from several pages.
- "supported" — the pages confirm it, allowing for paraphrase, and you can quote evidence.
- "unclear" — you genuinely cannot tell.

Reply with JSON only:
{{"verdict":"...","evidence":"exact phrase copied from the pages, or empty","conflict":{{"statement_says":"","pages_say":""}},"note":"one short sentence"}}

Leave `conflict` empty unless the verdict is "contradicted". Copy every quoted phrase verbatim
from the text above — never paraphrase it, and never invent it.
"""


def _coerce(out: dict) -> dict:
    v = str(out.get("verdict", "unclear")).lower().strip()
    conflict = out.get("conflict") or {}
    says, pages = str(conflict.get("statement_says", ""))[:300], str(conflict.get("pages_say", ""))[:300]
    # Demote an unevidenced contradiction rather than trusting it: the rubric's rule that a
    # finding without evidence is dropped applies to the triage layer too.
    if v == "contradicted" and not (says.strip() and pages.strip()):
        v, out = "incomplete", {**out, "note": "contradiction claimed without both phrases — demoted"}
    return {
        "verdict": v if v in RANK else "unclear",
        "evidence": str(out.get("evidence", ""))[:300],
        "conflict": {"statement_says": says, "pages_say": pages},
        "note": str(out.get("note", ""))[:300],
    }


_CLIENT = None


def ask_anthropic(model: str, prompt: str, timeout: int) -> dict:
    """Haiku via the API. Structured outputs guarantee the JSON contract rather than asking for it.

    No thinking and no effort parameter: this is a bounded classification, and the schema does
    the work a reasoning budget would otherwise be spent on.
    """
    global _CLIENT
    if _CLIENT is None:
        import anthropic

        _CLIENT = anthropic.Anthropic()
    resp = _CLIENT.with_options(timeout=timeout).messages.create(
        model=model,
        max_tokens=400,
        output_config={"format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return _coerce(json.loads(text))
    except json.JSONDecodeError:
        return {"verdict": "error", "note": "response was not valid JSON", "evidence": ""}


def ask(model: str, prompt: str, timeout: int) -> dict:
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 200},
        }
    ).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.loads(r.read())["response"]
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return {"verdict": "error", "note": "model did not return JSON", "evidence": ""}
    return _coerce(out)


def page_cache(book: corpus.Book) -> dict[tuple[str, int], str]:
    """{(label, printed_page): text} for every in-scope part, via form-feed splitting."""
    offset = book.meta.get("pdf_page_offset")
    cache: dict[tuple[str, int], str] = {}
    if offset is None:
        return cache
    for part in book.meta.get("parts", []):
        label = corpus.normalise_label(part["label"])
        if not any(p.label == label for p in book.in_scope):
            continue
        rng = figures.part_pdf_range(part)
        pdf = corpus.BOOKS / book.slug / part["file"]
        if not rng or not pdf.is_file():
            continue
        for pdf_page, text in figures.page_texts(pdf, *rng).items():
            cache[(label, pdf_page - offset)] = text
    return cache


def units(book: corpus.Book, kind: str) -> list[dict]:
    """Checkable units: claim blocks and ledger rows, each with one cited page."""
    md = book.deep_path.read_text()
    out: list[dict] = []

    if kind in ("claims", "both"):
        for b in verify.parse_blocks(md):
            if b.kind == "heading" or b.front_matter or b.synthesis:
                continue
            # The contradictions section exists to say that two pages disagree. Checking a
            # claim whose content *is* a contradiction against one of those pages flags it
            # every time — two of the first run's nine were exactly this.
            if any(_CONTRADICTION_RE.search(h) for h in b.heading_path):
                continue
            # A block's own locator wins; otherwise the enclosing heading's, which is part of
            # the locator grammar and covered a large slice of the summary the first run skipped.
            loc = next((l for l in b.locators if l.start), None) or next(
                (l for l in b.inherited if l.start), None
            )
            if not loc:
                continue
            text = " ".join(b.text.split())
            if len(text.split()) < 8:
                continue
            out.append({"kind": "claim", "line": b.line, "label": loc.label, "page": loc.start,
                        "page_end": loc.end or loc.start, "text": text[:1200]})

    if kind in ("ledger", "both"):
        in_ledger = False
        for i, line in enumerate(md.splitlines(), start=1):
            if line.startswith("## "):
                in_ledger = "identifier ledger" in line.lower()
                continue
            if not in_ledger or not (m := _LEDGER_ROW_RE.match(line)):
                continue
            locs = verify.parse_locators(m.group(4))
            loc = next((l for l in locs if l.start), None)
            if not loc:
                continue
            out.append(
                {
                    "kind": "ledger",
                    "line": i,
                    "label": loc.label,
                    "page": loc.start,
                    "page_end": loc.end or loc.start,
                    "text": f"{m.group(1).strip()} ({m.group(2).strip()}): {m.group(3).strip()}",
                }
            )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--backend", choices=["ollama", "anthropic"], default="ollama")
    ap.add_argument("--model", help="default: qwen2.5-coder locally, claude-haiku-4-5 on the API")
    ap.add_argument("--kind", choices=["claims", "ledger", "both"], default="both")
    ap.add_argument("--limit", type=int, help="stop after N units (for a trial run)")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--workers", type=int, default=8, help="parallel requests; API backend only")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    model = args.model or DEFAULT_MODEL[args.backend]
    backend = ask_anthropic if args.backend == "anthropic" else ask

    book = corpus.load(args.slug)
    if not book.deep_path.is_file():
        print(f"no summary at {book.deep_path}", file=sys.stderr)
        return 2

    todo = units(book, args.kind)
    if args.limit:
        todo = todo[: args.limit]
    pages = page_cache(book)
    print(f"{len(todo)} units · {len(pages)} pages cached · {args.backend}/{model}")
    print("triage raises suspicion only — a 'supported' verdict is NOT verification\n")

    def run(u: dict) -> dict:
        # A ledger row cites the page with the fullest definition, but supporting detail
        # legitimately sits on neighbouring pages. Reading only the cited page produced
        # "confirms X but is silent on Y" for a quarter of the first run.
        lo, hi = u["page"] - 1, u.get("page_end", u["page"]) + 1
        got = [(n, pages[(u["label"], n)]) for n in range(lo, hi + 1) if (u["label"], n) in pages]
        if not any(t.strip() for _, t in got):
            return {**u, "verdict": "no-page", "note": "cited pages not extractable", "evidence": ""}
        page_text = "\n\n".join(f"--- printed page {n} ---\n{t}" for n, t in got)
        span = f"printed pages {got[0][0]}-{got[-1][0]}" if len(got) > 1 else f"printed page {got[0][0]}"
        prompt = PROMPT.format(
            pages=span, label=u["label"], page_text=page_text[:14000], claim=u["text"]
        )
        try:
            return {**u, **backend(model, prompt, args.timeout)}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {**u, "verdict": "error", "note": f"{type(exc).__name__}: {exc}"[:200], "evidence": ""}
        except Exception as exc:  # noqa: BLE001 — one bad unit must not lose the whole run
            return {**u, "verdict": "error", "note": f"{type(exc).__name__}: {exc}"[:200], "evidence": ""}

    results, started = [], time.time()

    def tick(n: int) -> None:
        rate = n / max(1e-9, time.time() - started)
        print(f"  {n}/{len(todo)}  {rate:.2f}/s  eta {(len(todo) - n) / max(rate, 1e-9) / 60:.1f} min", end="\r")

    if args.backend == "anthropic" and args.workers > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for n, row in enumerate(pool.map(run, todo), start=1):
                results.append(row)
                if n % 5 == 0 or n == len(todo):
                    tick(n)
    else:
        for n, u in enumerate(todo, start=1):
            results.append(run(u))
            if n % 5 == 0 or n == len(todo):
                tick(n)

    if all(r["verdict"] == "error" for r in results) and results:
        print(f"\n\nevery unit errored — first: {results[0]['note']}", file=sys.stderr)
        return 3

    results.sort(key=lambda r: (RANK.get(r["verdict"], 9), r["line"]))
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    print("\n\n" + " · ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: RANK.get(kv[0], 9))))
    hints = [x for x in results if x["verdict"] in HINT_ONLY]
    if hints:
        print(f"\n{len(hints)} contradicted — recorded as hints, NOT passed to the reviewer.")
        print("  Two rounds measured this verdict at 17-22% precision; see ACTIONABLE in this file.")
    for r in [x for x in results if x["verdict"] in ACTIONABLE][:15]:
        print(f"\n  {r['kind']:<7} line {r['line']:<5} [{r['label']} p.{r['page']}]  {r['verdict'].upper()}")
        print(f"    claim: {r['text'][:150]}")
        print(f"    note:  {r['note'][:150]}")

    out = args.json or book.work_dir(ROOT) / "triage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"backend": args.backend, "model": model, "counts": counts, "units": results}, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
