#!/usr/bin/env python3
"""Run the pipeline from Python instead of Claude Code, on the same prompts.

    uv run python scripts/run.py distill  <slug> [--parts ch04,ch16]
    uv run python scripts/run.py assemble <slug>
    uv run python scripts/run.py review   <slug> [--round 1] [--summary PATH]

The Claude Code agents and this runner load the **same** `prompts/*.md` and the same specs.
That is the whole reason those files are not inlined in the agent definitions: two drivers,
one set of instructions, no drift. Edit the prompt, both change.

The difference is the mechanism. An agent uses tools to go and find its inputs; this assembles
them in Python and sends one request per stage. That suits these stages — each is "read a
known set of files, write one file" — and it makes runs reproducible, scriptable over a whole
corpus, and cheap to parallelise. It also gives up the thing the agents are good at: following
a lead the prompt did not anticipate. Use this for batch work over many books; use the agents
when a book is being worked on.

Bills the API. `ANTHROPIC_API_KEY` must be set — pass it inline rather than exporting it, so
it does not shadow Claude Code's OAuth login.
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-opus-5"
MAX_IMAGES = 30  # a chapter's page images; beyond this the request gets unwieldy


def client():
    import anthropic

    return anthropic.Anthropic()


def read(path: Path) -> str:
    return path.read_text(errors="replace")


def image_block(png: Path) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.standard_b64encode(png.read_bytes()).decode(),
        },
    }


def call(content: list[dict], effort: str, max_tokens: int = 32000) -> str:
    """One request, streamed.

    Streaming is not optional at these sizes: a digest runs to thousands of words and an
    assembled summary to twenty thousand, and a non-streaming request that large risks an
    HTTP timeout before the model has finished.
    """
    with client().messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise SystemExit(f"request refused: {getattr(msg, 'stop_details', None)}")
    return "".join(b.text for b in msg.content if b.type == "text")


def strip_fence(text: str) -> str:
    """Models sometimes wrap a whole markdown file in a fence. Unwrap it."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
    return "\n".join(lines).strip() + "\n"


# --- stages -----------------------------------------------------------------


def distill_one(book: corpus.Book, part: corpus.Part, effort: str) -> tuple[str, int, int]:
    pages = sorted((book.work_dir(ROOT) / "pages" / part.label).glob("p-*.png"))
    content: list[dict] = [
        {"type": "text", "text": read(ROOT / "prompts" / "distill.md")},
        {"type": "text", "text": read(ROOT / "spec" / "digest-format.md")},
        {"type": "text", "text": f"Book: {book.slug}. Part: {part.label} — {part.title}.\n"
                                 f"Printed pages {part.printed_start}-{part.printed_end}.\n"
                                 f"Scope note from meta.json: "
                                 f"{next((p.get('scope','') for p in book.meta['parts'] if corpus.normalise_label(p['label'])==part.label), '')}"},
        {"type": "text", "text": f"--- CHAPTER TEXT ({part.label}) ---\n{part.raw}"},
    ]
    for png in pages[:MAX_IMAGES]:
        content.append(image_block(png))
    if pages:
        content.append({"type": "text", "text": (
            f"The {min(len(pages), MAX_IMAGES)} images above are the pages of this chapter in "
            f"order, starting at printed page {part.printed_start}. Transcribe every figure "
            f"from them.")})
    content.append({"type": "text", "text": "Write the digest now. Output only the markdown."})

    out = book.work_dir(ROOT) / "digests" / f"{part.label}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = strip_fence(call(content, effort))
    out.write_text(text)
    return part.label, len(text.split()), len(pages)


def cmd_distill(book: corpus.Book, args) -> int:
    parts = book.in_scope
    if args.parts:
        want = {corpus.normalise_label(p) for p in args.parts.split(",")}
        parts = [p for p in parts if p.label in want]
    if not args.force:
        parts = [p for p in parts if not (book.work_dir(ROOT) / "digests" / f"{p.label}.md").is_file()]
    if not parts:
        print("nothing to do — every selected part already has a digest (use --force to redo)")
        return 0

    print(f"distilling {len(parts)} part(s) at effort {args.effort}: {', '.join(p.label for p in parts)}")
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for label, words, pages in pool.map(lambda p: distill_one(book, p, args.effort), parts):
            print(f"  {label:<8} {words:>6,} words · {pages} page images")
    print(f"{time.time() - started:.0f}s")
    return 0


def cmd_assemble(book: corpus.Book, args) -> int:
    digests = book.digest_paths(ROOT)
    if not digests:
        print("no digests to assemble", file=sys.stderr)
        return 2
    content = [
        {"type": "text", "text": read(ROOT / "prompts" / "assemble.md")},
        {"type": "text", "text": read(ROOT / "spec" / "summary-format.md")},
        {"type": "text", "text": f"Book metadata:\n{read(corpus.BOOKS / book.slug / 'meta.json')}"},
    ]
    for d in digests:
        content.append({"type": "text", "text": f"--- DIGEST {d.stem} ---\n{read(d)}"})
    content.append({"type": "text", "text": (
        "Write the deep summary now. Output only the markdown — no preamble, no fence. "
        "The brief is a separate request; do not write it here.")})

    print(f"assembling from {len(digests)} digests at effort {args.effort} …")
    deep = strip_fence(call(content, args.effort, max_tokens=64000))
    book.deep_path.write_text(deep)
    print(f"  deep  {len(deep.split()):>6,} words -> {book.deep_path}")

    brief = strip_fence(call([
        {"type": "text", "text": read(ROOT / "prompts" / "assemble.md")},
        {"type": "text", "text": f"--- THE DEEP SUMMARY ---\n{deep}"},
        {"type": "text", "text": (
            "Write ONLY the brief, per the spec: 1,200-1,800 words, standalone, derived from "
            "the deep summary above. Output only the markdown.")},
    ], args.effort, max_tokens=16000))
    book.brief_path.write_text(brief)
    print(f"  brief {len(brief.split()):>6,} words -> {book.brief_path}")
    return 0


def cmd_review(book: corpus.Book, args) -> int:
    summary = args.summary or book.deep_path
    work = book.work_dir(ROOT)
    content = [
        {"type": "text", "text": read(ROOT / "prompts" / "review.md")},
        {"type": "text", "text": read(ROOT / "rubric" / "summary-rubric.md")},
        {"type": "text", "text": f"--- THE SUMMARY UNDER REVIEW ({summary.name}) ---\n{read(summary)}"},
    ]
    for name in ("verify.json", "omissions.json", "triage-ledger.json", "triage-claims.json"):
        if (f := work / name).is_file():
            content.append({"type": "text", "text": f"--- {name} ---\n{read(f)[:200_000]}"})
    for d in book.digest_paths(ROOT):
        content.append({"type": "text", "text": f"--- DIGEST {d.stem} ---\n{read(d)}"})
    content.append({"type": "text", "text": (
        "Write the review now, in the format the prompt specifies. Output only the markdown.")})

    out = work / f"review-r{args.round}.md"
    print(f"reviewing {summary.name} at effort {args.effort} …")
    text = strip_fence(call(content, args.effort, max_tokens=32000))
    out.write_text(text)
    print(f"  {len(text.split()):,} words -> {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="stage", required=True)
    for name in ("distill", "assemble", "review"):
        s = sub.add_parser(name)
        s.add_argument("slug")
        # Measured on ch13 of sip-johnston: high gave 86 claims / 76 identifiers against the
        # Claude Code agent's 105 / 100; xhigh gave 102 / 89 with zero uncited bullets, for
        # roughly the same output length. Effort bought density, not verbosity.
        s.add_argument("--effort", default="xhigh", choices=["low", "medium", "high", "xhigh", "max"])
        if name == "distill":
            s.add_argument("--parts")
            s.add_argument("--workers", type=int, default=4)
            s.add_argument("--force", action="store_true")
        if name == "review":
            s.add_argument("--round", type=int, default=1)
            s.add_argument("--summary", type=Path)
    args = ap.parse_args()

    book = corpus.load(args.slug)
    return {"distill": cmd_distill, "assemble": cmd_assemble, "review": cmd_review}[args.stage](book, args)


if __name__ == "__main__":
    raise SystemExit(main())
