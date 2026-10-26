"""Phase 1 (Indexer) LangChain tools.

These tools let the Indexer agent inspect a physics PDF with PyMuPDF (fitz),
locate question/solution page boundaries, and fill in the pre-registered
paper row in SQLite.

Pipeline context (READ CAREFULLY):
- Python pre-flight (``database.register_paper``, exposed via the
  ``preflight.py`` entry point) has ALREADY created the
  papers row and computed the PDF hash. The ``paper_id`` is injected into
  LangGraph state by Python -- the agent MUST take it from state and MUST
  NOT invent, guess, or recompute hashes.
- The agent NEVER supplies ``pdf_hash``; there is no hash parameter on any
  tool. Duplicate prevention happened in pre-flight.

Routing contract for the LLM:
- Always call ``get_pdf_info`` first. If ``has_text_layer`` is False, ABORT
  gracefully (the PDF is a scanned image and text search is unreliable) --
  do not call ``search_pdf_text`` / ``get_page_text``.
- Use ``search_pdf_text`` to find candidate pages for a query, then
  ``get_page_text`` to confirm boundaries.
- Finish with ``submit_metadata_and_boundaries`` (an UPDATE of the existing
  row identified by ``paper_id`` from graph state) to persist the discovered
  metadata.
"""

from __future__ import annotations

import fitz  # PyMuPDF
from langchain_core.tools import tool

import database


def _check_range(name: str, value: int | None, minimum: int) -> None:
    """Validate a 1-based page boundary (int, >= minimum)."""
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")


@tool
def get_pdf_info(pdf_path: str) -> dict:
    """Inspect a PDF file and report its basic structure.

    Call this before any other PDF tool.

    Args:
        pdf_path: Filesystem path to the PDF file.

    Returns:
        A dict {"page_count": int, "has_text_layer": bool}. If
        has_text_layer is False, ABORT: do not call search_pdf_text or
        get_page_text (scanned/image-only PDF).
    """
    doc = fitz.open(pdf_path)
    try:
        page_count = len(doc)
        has_text = False
        for page in doc:
            if page.get_text().strip():
                has_text = True
                break
        return {"page_count": page_count, "has_text_layer": has_text}
    finally:
        doc.close()


@tool
def search_pdf_text(pdf_path: str, query: str) -> list[int]:
    """Search a text-layer PDF for a query string (case-insensitive).

    Args:
        pdf_path: Filesystem path to the PDF file.
        query: Target substring, e.g. "Question 15" or "Solutions".

    Returns:
        1-based page numbers containing the query (first page is 1, not
        0). Empty list if no page matches.
    """
    needle = query.lower()
    doc = fitz.open(pdf_path)
    try:
        hits: list[int] = []
        for i, page in enumerate(doc):
            if needle in page.get_text().lower():
                hits.append(i + 1)  # 1-based
        return hits
    finally:
        doc.close()


@tool
def get_page_text(pdf_path: str, page_number: int) -> str:
    """Return the raw extracted text of one PDF page.

    Args:
        pdf_path: Filesystem path to the PDF file.
        page_number: 1-based page number, within get_pdf_info's page_count.

    Returns:
        The raw page text. Raises ValueError if out of range.
    """
    doc = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(
                f"page_number {page_number} out of range 1..{len(doc)}"
            )
        return doc[page_number - 1].get_text()
    finally:
        doc.close()


@tool
def submit_metadata_and_boundaries(
    paper_id: int,
    paper_name: str,
    exam_type: str,
    paper_date: str,
    source_institute: str,
    q_start: int,
    q_end: int,
    sol_section_start: int,
    s_start: int | None = None,
    s_end: int | None = None,
) -> bool:
    """Save the paper's metadata and physics page boundaries.

    Args:
        paper_id: From LangGraph state; use verbatim, never invent.
        paper_name: Paper title, e.g. "JEE Advanced 2024 Paper 1".
        exam_type: Exam category, e.g. "JEE", "NEET", "Olympiad".
        paper_date: Date string, e.g. "2024-05-26".
        source_institute: Institute or publisher, e.g. "IIT Madras".
        q_start: 1-based first page of the questions section (>= 1).
        q_end: 1-based last page of the questions section (>= q_start).
        sol_section_start: REQUIRED section flag, always pass explicitly:
            0 = no solutions anywhere in this paper;
            1 = separate solution PDF (its key/solutions start at its p.1);
            N > 1 = combined single file: the solutions section (key table
            page if one exists, else the first solution page) starts at
            page N of the QUESTION file. Python splits the file there so
            the extractor sees two files.
        s_start: 1-based first page of the physics SOLUTIONS (key table
            excluded), in original file pages, or None/0 when there are
            no solutions.
        s_end: 1-based last page of the physics solutions (>= s_start),
            or None/0 when there are no solutions.

    Returns:
        True on success; resubmitting overwrites. Invalid paper_id or
        boundaries fail.
    """
    # Prompt convention: the agent passes 0 for missing solution boundaries.
    if s_start == 0:
        s_start = None
    if s_end == 0:
        s_end = None
    if not isinstance(sol_section_start, int) or isinstance(
        sol_section_start, bool
    ):
        raise ValueError(
            f"sol_section_start must be an integer, got {sol_section_start!r}"
        )
    if sol_section_start < 0:
        raise ValueError(
            f"sol_section_start must be >= 0, got {sol_section_start!r}"
        )
    _check_range("q_start", q_start, minimum=1)
    _check_range("q_end", q_end, minimum=q_start)
    if s_start is not None:
        _check_range("s_start", s_start, minimum=1)
    if s_end is not None:
        _check_range("s_end", s_end, minimum=s_start if s_start is not None else 1)
    if (s_start is None) != (s_end is None):
        raise ValueError("s_start and s_end must either both be set or both be null")
    if sol_section_start == 0 and (s_start is not None or s_end is not None):
        raise ValueError("sol_section_start=0 means no solutions: pass s as 0 too")
    if sol_section_start >= 1 and (s_start is None or s_end is None):
        raise ValueError(
            "sol_section_start>=1 means solutions exist: s_start/s_end required"
        )
    database.init_db()
    conn = database.get_connection()
    try:
        row = conn.execute(
            "SELECT question_pdf_path, solution_pdf_path FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"paper_id {paper_id} does not exist; "
                "it must come from pre-flight registration via LangGraph state"
            )
        import os as _os

        q_path, s_path = row["question_pdf_path"], row["solution_pdf_path"]
        combined = bool(s_path) and bool(q_path) and _os.path.realpath(
            s_path) == _os.path.realpath(q_path)
        if combined:
            # Combined single file: split point lives in the question file,
            # after the questions, at or before the first solution page.
            if sol_section_start <= 1:
                raise ValueError(
                    "combined file (solution == question): sol_section_start "
                    f"must be > 1, got {sol_section_start}"
                )
            if not (q_end < sol_section_start <= s_start):
                raise ValueError(
                    "combined file: need q_end < sol_section_start <= s_start, "
                    f"got q {q_start}-{q_end}, split {sol_section_start}, "
                    f"s {s_start}-{s_end}"
                )
        elif sol_section_start > 1:
            raise ValueError(
                "sol_section_start > 1 is only for a combined single file "
                "(solution == question); separate PDFs must pass 1, "
                "questions-only must pass 0"
            )
        cur = conn.execute(
            """
            UPDATE papers SET
                paper_name = ?,
                exam_type = ?,
                paper_date = ?,
                source_institute = ?,
                q_start = ?,
                q_end = ?,
                s_start = ?,
                s_end = ?,
                sol_section_start = ?
            WHERE id = ?
            """,
            (
                paper_name,
                exam_type,
                paper_date,
                source_institute,
                q_start,
                q_end,
                s_start,
                s_end,
                sol_section_start,
                paper_id,
            ),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(
                f"paper_id {paper_id} does not exist; "
                "it must come from pre-flight registration via LangGraph state"
            )
        return True
    finally:
        conn.close()
