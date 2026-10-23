"""Phase 1 runner: register PDFs -> invoke the Indexer graph -> report.

Usage:
    python run_indexer.py <question_pdf> [<solution_pdf>]

Prints Status, Time Taken, Tokens Used, and the final papers row to prove
the metadata UPDATE landed.
"""

from __future__ import annotations

import sys
import time

import config  # noqa: F401 -- must be first: pins env from config.yaml + .env
import database
from graph import initial_state, phase1_app
from preflight import preflight_register


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
    if not (1 <= len(args) <= 2):
        print(f"Usage: {sys.argv[0] if argv is None else 'run_indexer.py'} "
              "<question_pdf> [<solution_pdf>]")
        return 1
    question_pdf, solution_pdf = args[0], (args[1] if len(args) == 2 else None)

    try:
        paper_id = preflight_register(question_pdf, solution_pdf)
        print(f"Registered paper_id={paper_id}")
    except database.DuplicatePaperError:
        row = database.find_paper_by_hash(
            database.compute_paper_hash(question_pdf, solution_pdf)
        )
        paper_id = int(row["id"])
        print(f"Already registered, reusing paper_id={paper_id}")
    except FileNotFoundError as exc:
        print(f"PDF not found: {exc}")
        return 1

    state = initial_state(paper_id, question_pdf, solution_pdf)
    start = time.time()
    try:
        final = phase1_app.invoke(state, config={"recursion_limit": 25})
    except Exception as exc:
        print(f"Graph run failed: {type(exc).__name__}: {exc}")
        return 1
    elapsed = time.time() - start
    final["execution_time_sec"] = elapsed

    tokens = _summarize_tokens(final)
    row = database.get_paper(paper_id)

    print("---- Phase 1 summary ----")
    print(f"Status:       {final.get('status')}")
    print(f"Time Taken:   {elapsed:.2f}s")
    print(f"Prompt Tokens:      {tokens['prompt_tokens']}")
    print(f"Completion Tokens:  {tokens['completion_tokens']}")
    print(f"Total Tokens:       {tokens['total_tokens']}")
    print(f"DB row:       {dict(row) if row else None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
