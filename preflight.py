"""System pre-flight entry point (Python, outside the AI).

Usage::

    python preflight.py <question_pdf> [<solution_pdf>]

Computes the combined hash, aborts on duplicates, INSERTs the stub papers
row (paths + hash + archive=0) and prints the stable ``paper_id`` for
LangGraph state initialisation::

    {"paper_id": <id>, "question_pdf_path": ..., "solution_pdf_path": ...}
"""

from __future__ import annotations

import sys

import config  # noqa: F401 -- must be first: pins DB/Outputs paths from config.yaml
import database


def preflight_register(question_pdf_path: str, solution_pdf_path: str | None = None) -> int:
    """Register a PDF pair and return its stable ``paper_id``.

    Raises:
        database.DuplicatePaperError: If this exact PDF pair was ingested before.
    """
    return database.register_paper(question_pdf_path, solution_pdf_path)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not (1 <= len(args) <= 2):
        print(f"Usage: {sys.argv[0] if argv is None else 'preflight.py'} "
              "<question_pdf> [<solution_pdf>]", file=sys.stderr)
        return 1
    q = args[0]
    s = args[1] if len(args) == 2 else None
    try:
        paper_id = preflight_register(q, s)
    except database.DuplicatePaperError as exc:
        print(f"Duplicate PDF pair, aborting: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"PDF not found: {exc}", file=sys.stderr)
        return 1
    print(paper_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
