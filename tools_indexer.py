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

    Use this tool FIRST before any other PDF tool to decide whether the
    document is machine-readable.

    Args:
        pdf_path: Absolute or relative filesystem path to the PDF file.

    Returns:
        A dict {"page_count": int, "has_text_layer": bool}.
        ``has_text_layer`` is True if at least one page yields non-whitespace
        extractable text, else False. If False, the agent must ABORT gracefully
        and must NOT call search_pdf_text or get_page_text, because the PDF
        is scanned/image-only.
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

    Call this AFTER get_pdf_info confirms has_text_layer is True. Use it to
    locate candidate pages, e.g. query "Question 15" or "Solutions".

    Args:
        pdf_path: Filesystem path to the PDF file.
        query: Target substring to search for (case-insensitive).

    Returns:
        A list of 1-based page numbers containing the query. Empty list if
        no page matches. Pages are 1-based: the first page is 1, not 0.
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

    Use this to confirm question/solution boundaries found via search_pdf_text.

    Args:
        pdf_path: Filesystem path to the PDF file.
        page_number: 1-based page number (first page is 1). Must satisfy
            1 <= page_number <= page_count from get_pdf_info.

    Returns:
        The raw text of the specified page. Raises ValueError if the page
        number is out of range.
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
    s_start: int | None = None,
    s_end: int | None = None,
) -> bool:
    """UPDATE the pre-registered paper row with discovered metadata/boundaries.

    Call this after boundaries are verified via get_page_text. This is an
    UPDATE of the stub row created by Python pre-flight
    (``database.register_paper``) -- it INSERTs nothing and takes no hash.
    The ``paper_id`` comes from LangGraph graph state (injected by Python);
    use it verbatim and NEVER invent a paper_id or compute a PDF hash.
    Re-calling with the same ``paper_id`` overwrites the previous values,
    so corrections simply resubmit.

    Args:
        paper_id: Integer PK from LangGraph state (pre-flight registration).
            Must already exist in the papers table.
        paper_name: Human-readable paper title, e.g. "JEE Advanced 2024 Paper 1".
        exam_type: Exam category, e.g. "JEE", "NEET", "Olympiad".
        paper_date: Date string, e.g. "2024-05-26".
        source_institute: Institute or publisher, e.g. "IIT Madras".
        q_start: 1-based first page of the questions section (>= 1).
        q_end: 1-based last page of the questions section (>= q_start).
        s_start: 1-based first page of the solutions section, or null/None
            when the paper has no solutions.
        s_end: 1-based last page of the solutions section (>= s_start),
            or null/None when the paper has no solutions.

    Returns:
        True on success. Fails with an error if ``paper_id`` does not exist
        or any boundary is invalid (< 1, or start > end).
    """
    _check_range("q_start", q_start, minimum=1)
    _check_range("q_end", q_end, minimum=q_start)
    if s_start is not None:
        _check_range("s_start", s_start, minimum=1)
    if s_end is not None:
        _check_range("s_end", s_end, minimum=s_start if s_start is not None else 1)
    if (s_start is None) != (s_end is None):
        raise ValueError("s_start and s_end must either both be set or both be null")
    database.init_db()
    conn = database.get_connection()
    try:
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
                s_end = ?
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
