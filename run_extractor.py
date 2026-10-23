"""Phase 2 runner: extract a paper that already passed Phase 1.

Usage:
    python run_extractor.py <paper_id>

Starts the graph directly at extractor_init (Phase 1 bypassed): boundaries
and PDF paths are reloaded from the database for the given paper_id.
Prints Status, Time Taken, and Token Usage at the end.
"""

from __future__ import annotations

import sys
import time

import config  # noqa: F401 -- must be first: pins env from config.yaml + .env
import database
from graph import extractor_app


def _summarize_tokens(state: dict) -> dict:
    """Prefer node-accumulated totals; fall back to summing message metadata."""
    usage = state.get("token_usage") or {}
    if usage.get("total_tokens"):
        return usage
    prompt = completion = 0
    for msg in state.get("messages") or []:
        meta = getattr(msg, "usage_metadata", None) or {}
        prompt += meta.get("input_tokens", 0)
        completion += meta.get("output_tokens", 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(f"Usage: {sys.argv[0] if argv is None else 'run_extractor.py'} <paper_id>")
        return 1
    try:
        paper_id = int(args[0])
    except ValueError:
        print(f"paper_id must be an integer, got {args[0]!r}")
        return 1

    row = database.get_paper(paper_id)
    if row is None:
        print(f"paper_id {paper_id} does not exist")
        return 1
    if row["q_start"] is None:
        print(f"paper_id {paper_id} has no Phase 1 boundaries (aborted?) -- nothing to extract")
        return 1
    print(
        f"Extracting paper_id={paper_id} "
        f"(Q pp. {row['q_start']}-{row['q_end']}, "
        f"S pp. {row['s_start']}-{row['s_end']})"
    )

    start = time.time()
    try:
        final = extractor_app.invoke(
            {"paper_id": paper_id, "messages": []},
            config={"recursion_limit": 100},
        )
    except Exception as exc:
        print(f"Graph run failed: {type(exc).__name__}: {exc}")
        return 1
    elapsed = time.time() - start
    final["execution_time_sec"] = elapsed

    tokens = _summarize_tokens(final)
    print("---- Phase 2 summary ----")
    print(f"Status:       {final.get('status')}")
    print(f"Time Taken:   {elapsed:.2f}s")
    print(f"Prompt Tokens:      {tokens['prompt_tokens']}")
    print(f"Completion Tokens:  {tokens['completion_tokens']}")
    print(f"Total Tokens:       {tokens['total_tokens']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
