"""Phase 1 runner: register PDFs -> invoke the Indexer graph -> report.

Usage:
    python run_indexer.py <question_pdf> [<solution_pdf>]

    Combined single file (Q + Key + Sol in one PDF): pass the same
    path twice -- the indexer reports sol_section_start and the
    splitter hands the extractor two files.


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
from run_pipeline import summarize_tokens


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

    prev_status = database.get_paper(paper_id)["status"]
    if prev_status == "done":
        print(f"paper_id={paper_id} already done (re-run via pipeline --force)")
        return 1
    database.set_paper_status(paper_id, "indexing")
    state = initial_state(paper_id, question_pdf, solution_pdf)
    start = time.time()
    try:
        final = phase1_app.invoke(state, config={"recursion_limit": 25})
    except Exception as exc:
        database.set_paper_status(
            paper_id, "failed", f"{type(exc).__name__}: {exc}", time.time() - start
        )
        print(f"Graph run failed: {type(exc).__name__}: {exc}")
        return 1
    elapsed = time.time() - start
    final["execution_time_sec"] = elapsed
    if final.get("status") == "aborted_no_text":
        database.set_paper_status(paper_id, "failed", "no text layer", elapsed)
    elif final.get("status") == "split_failed":
        database.set_paper_status(paper_id, "failed", "combined split failed",
                                  elapsed)
    else:
        # Indexed, awaiting extraction -> back to the queue.
        database.set_paper_status(paper_id, "uploaded")

    tokens = summarize_tokens(paper_id)["total"]
    row = database.get_paper(paper_id)

    print("---- Phase 1 summary ----")
    print(f"Status:       {final.get('status')}")
    print(f"Time Taken:   {elapsed:.2f}s")
    print(f"Prompt Tokens:      {tokens['input']} "
          f"(fresh {tokens['fresh_input']}, cached {tokens['cache_read']})")
    print(f"Completion Tokens:  {tokens['output']} "
          f"(reasoning {tokens['reasoning']})")
    print(f"Total Tokens:       {tokens['input'] + tokens['output']}")
    print(f"DB row:       {dict(row) if row else None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
