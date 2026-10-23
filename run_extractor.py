"""Phase 2 runner: extract a paper that has already passed Phase 1.

Usage:
    python run_extractor.py <paper_id>

Starts the graph directly at extractor_init (Phase 1 bypassed): boundaries
and PDF paths are reloaded from the database for the given paper_id.
Prints a per-turn token log (input / cache_read / reasoning), a coverage
report, and the completion gate outcome.
"""

from __future__ import annotations

import os
import sys
import time

import config  # noqa: F401 -- must be first: pins env from config.yaml + .env
import database
import directory_manager
from graph import extractor_app


def _per_turn_log(messages: list) -> None:
    print("---- per-turn log (idx, in, cache_read, reasoning_out) ----")
    for i, m in enumerate(messages):
        u = getattr(m, "usage_metadata", None)
        if not u:
            continue
        in_det = u.get("input_token_details", {}) or {}
        out_det = u.get("output_token_details", {}) or {}
        print(
            f"  turn-msg {i:3d} {type(m).__name__[:12]:12s} "
            f"in={u.get('input_tokens', 0):7d} "
            f"cache_read={in_det.get('cache_read', 0):7d} "
            f"reasoning={out_det.get('reasoning', 0):6d} "
            f"out={u.get('output_tokens', 0):6d}"
        )


def _coverage(paper_id: int) -> tuple[list[str], list[str]]:
    """Return (submitted question_numbers, those missing solution.tex)."""
    base = directory_manager.get_question_dir(paper_id, "__probe__").parent
    submitted, missing = [], []
    if not base.is_dir():
        return submitted, missing
    for qdir in sorted(base.iterdir()):
        if not qdir.is_dir():
            continue
        if (qdir / directory_manager.QUESTION_TEX).is_file():
            submitted.append(qdir.name)
            if not (qdir / directory_manager.SOLUTION_TEX).is_file():
                missing.append(qdir.name)
    return submitted, missing


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

    def run_once(messages: list) -> dict:
        start = time.time()
        try:
            final = extractor_app.invoke(
                {"paper_id": paper_id, "messages": messages},
                config={"recursion_limit": 200},
            )
        except Exception as exc:
            print(f"Graph run failed: {type(exc).__name__}: {exc}")
            raise SystemExit(1)
        final["execution_time_sec"] = time.time() - start
        return final

    t0 = time.time()
    final = run_once([])
    submitted, missing = _coverage(paper_id)

    # Completion gate: every submitted question needs its solution on disk.
    # Resume once with the gap list instead of starting over.
    resumed = False
    if missing and row["s_start"] is not None:
        resumed = True
        print(f"Completion gate: missing solutions for {missing} -- resuming once")
        gap = (
            f"Not yet submitted solutions for: {', '.join(missing)}. "
                "Continue with those now."
        )
        from langchain_core.messages import HumanMessage

        final = run_once(list(final["messages"]) + [HumanMessage(content=gap)])
        submitted, missing = _coverage(paper_id)

    elapsed = time.time() - t0
    _per_turn_log(final["messages"])
    print("---- Phase 2 summary ----")
    print(f"Status:       {final.get('status')}")
    print(f"Time Taken:   {elapsed:.2f}s (resumed: {resumed})")
    print(f"Submitted questions: {submitted}")
    print(f"Missing solutions:   {missing or 'none'}")
    print(f"Outputs at:   {os.path.join(config.OUTPUT_BASE, str(paper_id))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
