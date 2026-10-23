"""Combined pipeline: register -> index -> extract, with status + tokens.

Usage:
    python3 run_pipeline.py <question_pdf> [<solution_pdf>] [--force]

Runs Phase 1 then Phase 2 in one flow (existing completion gate, one resume
max), tracking papers.status (uploaded/indexing/extracting/done/failed) and
per-message token rows. Refuses papers already done unless --force, which
wipes that paper's Outputs, question rows and token rows first.
"""

from __future__ import annotations

import os
import shutil
import sys
import time

import config  # noqa: F401 -- must be first: pins env from config.yaml + .env
import database
import directory_manager
from graph import extractor_app, initial_state, phase1_app
from preflight import preflight_register
from run_extractor import _coverage


def _wipe_paper(paper_id: int) -> None:
    """Clear a paper's Outputs, question rows and token rows for a fresh run."""
    out = directory_manager.paper_dir(paper_id)
    if out.is_dir():
        shutil.rmtree(out)
    conn = database.get_connection()
    try:
        conn.execute("DELETE FROM questions WHERE paper_id = ?", (paper_id,))
        conn.execute("DELETE FROM token_usage WHERE paper_id = ?", (paper_id,))
        conn.commit()
    finally:
        conn.close()


def summarize_tokens(paper_id: int) -> dict:
    """Aggregate token_usage rows: per phase, totals, fresh input, cost."""
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT phase, input, cache_read, output, reasoning, ts"
            " FROM token_usage WHERE paper_id = ? ORDER BY id",
            (paper_id,),
        ).fetchall()
    finally:
        conn.close()
    phases: dict = {}
    for r in rows:
        p = phases.setdefault(
            r["phase"],
            {"turns": 0, "input": 0, "cache_read": 0, "output": 0, "reasoning": 0},
        )
        p["turns"] += 1
        p["input"] += r["input"] or 0
        p["cache_read"] += r["cache_read"] or 0
        p["output"] += r["output"] or 0
        p["reasoning"] += r["reasoning"] or 0
    total = {
        "turns": sum(p["turns"] for p in phases.values()),
        "input": sum(p["input"] for p in phases.values()),
        "cache_read": sum(p["cache_read"] for p in phases.values()),
        "output": sum(p["output"] for p in phases.values()),
        "reasoning": sum(p["reasoning"] for p in phases.values()),
    }
    total["fresh_input"] = total["input"] - total["cache_read"]
    pricing = config.PRICING
    cost = (
        total["fresh_input"] / 1e6 * pricing["input_per_mtok"]
        + total["cache_read"] / 1e6 * pricing["cache_read_per_mtok"]
        + total["output"] / 1e6 * pricing["output_per_mtok"]
    )
    return {"per_phase": phases, "total": total, "cost_usd": cost}


def run_pipeline(paper_id: int, force: bool = False) -> dict:
    """Run indexer then extractor for a registered paper.

    Returns {"paper_id", "status", "summary", "elapsed_sec"}.
    Raises ValueError if the paper is unknown or already done (without force).
    Any mid-run failure marks the paper failed with the error recorded.
    """
    row = database.get_paper(paper_id)
    if row is None:
        raise ValueError(f"paper_id {paper_id} does not exist")
    if row["status"] == "done" and not force:
        raise ValueError(f"paper_id {paper_id} already done (use force=True to rerun)")
    if force:
        _wipe_paper(paper_id)

    t0 = time.time()
    try:
        database.set_paper_status(paper_id, "indexing")
        qpdf = database.get_paper(paper_id)["question_pdf_path"]
        spdf = database.get_paper(paper_id)["solution_pdf_path"]
        final1 = phase1_app.invoke(
            initial_state(paper_id, qpdf, spdf), config={"recursion_limit": 25}
        )
        if final1.get("status") == "aborted_no_text":
            elapsed = time.time() - t0
            database.set_paper_status(paper_id, "failed", "no text layer", elapsed)
            return {
                "paper_id": paper_id,
                "status": "failed",
                "summary": summarize_tokens(paper_id),
                "elapsed_sec": elapsed,
            }

        database.set_paper_status(paper_id, "extracting")
        final = extractor_app.invoke(
            {"paper_id": paper_id, "messages": []},
            config={"recursion_limit": 200},
        )
        submitted, missing = _coverage(paper_id)
        elapsed = time.time() - t0
        if missing:
            crow = database.get_paper(paper_id)
            if crow["s_start"] is not None:
                from langchain_core.messages import HumanMessage

                final = extractor_app.invoke(
                    {
                        "paper_id": paper_id,
                        "messages": list(final["messages"])
                        + [
                            HumanMessage(
                                content="Not yet submitted solutions for: "
                                + ", ".join(missing)
                                + ". Continue with those now."
                            )
                        ],
                    },
                    config={"recursion_limit": 200},
                )
                submitted, missing = _coverage(paper_id)
                elapsed = time.time() - t0
        if missing:
            database.set_paper_status(
                paper_id, "failed", f"missing solutions: {', '.join(missing)}", elapsed
            )
            status = "failed"
        else:
            database.set_paper_status(paper_id, "done", elapsed_sec=elapsed)
            status = "done"
        return {
            "paper_id": paper_id,
            "status": status,
            "summary": summarize_tokens(paper_id),
            "elapsed_sec": elapsed,
        }
    except Exception as exc:
        database.set_paper_status(
            paper_id, "failed", f"{type(exc).__name__}: {exc}", time.time() - t0
        )
        raise


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    if not (1 <= len(args) <= 2):
        print(f"Usage: {sys.argv[0] if argv is None else 'run_pipeline.py'} "
              "<question_pdf> [<solution_pdf>] [--force]")
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

    try:
        result = run_pipeline(paper_id, force=force)
    except ValueError as exc:
        print(exc)
        return 1
    except Exception as exc:
        print(f"Pipeline run failed: {type(exc).__name__}: {exc}")
        return 1

    s = result["summary"]
    print("---- Pipeline summary ----")
    print(f"Status:       {result['status']}")
    print(f"Time Taken:   {result['elapsed_sec']:.2f}s")
    for phase, p in s["per_phase"].items():
        print(
            f"  {phase}: turns={p['turns']} in={p['input']} "
            f"cached={p['cache_read']} out={p['output']} rsn={p['reasoning']}"
        )
    t = s["total"]
    print(
        f"  TOTAL: turns={t['turns']} in={t['input']} fresh={t['fresh_input']} "
        f"cached={t['cache_read']} out={t['output']} rsn={t['reasoning']}"
    )
    print(f"Cost:         ${s['cost_usd']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
