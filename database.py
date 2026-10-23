"""SQLite persistence layer for the physics PDF extraction pipeline.

Database file: resolved by ``config.py`` (``config.yaml`` >
``PHYSICS_ARCHIVE_DB`` env > default ``physics_archive.db`` next to the
source). Every entry point must ``import config`` before this module so all
stages share one database file.

Corrected pipeline flow
-----------------------
1. **System pre-flight (Python, outside the AI):** call
   :func:`register_paper` with the question/solution PDF paths. Python
   computes the combined SHA-256 hash, aborts on duplicates, INSERTs a stub
   row (paths + hash + ``archive = 0``, everything else NULL) and returns the
   stable ``paper_id``.
2. **State init (LangGraph):** Python puts ``paper_id`` + PDF paths in graph state.
3. **Phase 1 (Indexer agent):** discovers metadata/boundaries with read-only
   PDF tools, then calls the ``submit_metadata_and_boundaries`` LangChain
   tool, which is an **UPDATE by paper_id** -- the agent never computes or
   supplies hashes.
4. **Phase 2 (Extractor agent):** ``paper_id`` again comes from graph state;
   all submit/crop tools overwrite idempotently so corrections reuse the
   same filename.

Tables
------
papers
    id (PK, integer), paper_name (text), exam_type (text), paper_date (text),
    source_institute (text), question_pdf_path (text), solution_pdf_path (text),
    pdf_hash (text, unique), archive (integer, default 0),
    plus nullable boundary columns q_start, q_end, s_start, s_end.
    ``archive`` lifecycle: 0 = in progress, 1 = terminal (completed or
    intentionally skipped, e.g. no text layer). An aborted paper is
    recognizable as ``archive = 1`` with metadata still NULL -- nothing was
    ever extracted, so no metadata was ever written. Use
    :func:`mark_paper_archived` for the transition; never set it by hand.
questions
    id (PK, integer), paper_id (FK -> papers.id), question_number (text),
    latex_folder (text), status (text, default 'draft').
    question_number is TEXT to support grouped comprehensions such as
    "15-17_paragraph" or "15a".
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import config  # noqa: F401 -- must precede DB_PATH: pins env from config.yaml

# Resolve DB path: explicit env override wins (useful for pytest tmp dirs),
# otherwise physics_archive.db next to this file / project root.
DB_PATH = Path(os.environ.get("PHYSICS_ARCHIVE_DB", Path(__file__).parent / "physics_archive.db"))

SCHEMA_PAPERS = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_name TEXT,
    exam_type TEXT,
    paper_date TEXT,
    source_institute TEXT,
    question_pdf_path TEXT,
    solution_pdf_path TEXT,
    pdf_hash TEXT UNIQUE,
    archive INTEGER DEFAULT 0,
    q_start INTEGER,
    q_end INTEGER,
    s_start INTEGER,
    s_end INTEGER,
    status TEXT DEFAULT 'uploaded',
    error TEXT,
    elapsed_sec REAL
);
"""

SCHEMA_TOKEN_USAGE = """
CREATE TABLE IF NOT EXISTS token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    phase TEXT NOT NULL,
    input INTEGER NOT NULL DEFAULT 0,
    cache_read INTEGER NOT NULL DEFAULT 0,
    output INTEGER NOT NULL DEFAULT 0,
    reasoning INTEGER NOT NULL DEFAULT 0,
    ts TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
);
"""

SCHEMA_QUESTIONS = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    question_number TEXT NOT NULL,
    latex_folder TEXT,
    status TEXT DEFAULT 'draft',
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    UNIQUE (paper_id, question_number)
);
"""


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Return a SQLite connection with foreign keys enforced."""
    path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path | None = None) -> Path:
    """Create tables if missing; migrate old DBs (status/error/token_usage).

    Returns the path of the database file used.
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    # Ensure parent dir exists (no-op for project root).
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(path)
    try:
        conn.execute(SCHEMA_PAPERS)
        conn.execute(SCHEMA_QUESTIONS)
        conn.execute(SCHEMA_TOKEN_USAGE)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(papers)")}
        if "status" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN status TEXT DEFAULT 'uploaded'")
        if "error" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN error TEXT")
        if "elapsed_sec" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN elapsed_sec REAL")
        conn.commit()
    finally:
        conn.close()
    return path


class DuplicatePaperError(ValueError):
    """Raised by :func:`register_paper` when the PDF pair was already ingested."""


def compute_paper_hash(question_pdf_path: str, solution_pdf_path: str | None = None) -> str:
    """Compute the stable combined SHA-256 hash of a question/solution PDF pair.

    Bytes of the question PDF are hashed first, then (if given) the solution
    PDF. The pair together therefore maps to exactly one hash, so the same
    set of PDFs can never enter Phase 1 twice.

    Args:
        question_pdf_path: Path to the questions PDF.
        solution_pdf_path: Path to the solutions PDF, or None if absent.

    Returns:
        Hex digest string stored in ``papers.pdf_hash``.
    """
    h = hashlib.sha256()
    for path in (question_pdf_path,) if solution_pdf_path is None else (
        question_pdf_path,
        solution_pdf_path,
    ):
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    return h.hexdigest()


def find_paper_by_hash(pdf_hash: str) -> sqlite3.Row | None:
    """Return the papers row with this hash, or None if not ingested."""
    init_db()
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM papers WHERE pdf_hash = ?", (pdf_hash,)
        ).fetchone()
    finally:
        conn.close()


def get_paper(paper_id: int) -> sqlite3.Row | None:
    """Return the papers row for ``paper_id``, or None if it does not exist."""
    init_db()
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
    finally:
        conn.close()


def set_paper_status(
    paper_id: int,
    status: str,
    error: str | None = None,
    elapsed_sec: float | None = None,
) -> None:
    """Set a paper's pipeline status (uploaded/indexing/extracting/done/failed).

    Passing ``error`` records the failure reason (use with "failed").
    ``elapsed_sec`` records wall time when known (set on terminal states).
    Raises ValueError for an unknown paper_id.
    """
    init_db()
    conn = get_connection()
    try:
        if elapsed_sec is None:
            cur = conn.execute(
                "UPDATE papers SET status = ?, error = ? WHERE id = ?",
                (status, error, paper_id),
            )
        else:
            cur = conn.execute(
                "UPDATE papers SET status = ?, error = ?, elapsed_sec = ? WHERE id = ?",
                (status, error, elapsed_sec, paper_id),
            )
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"paper_id {paper_id} does not exist")
    finally:
        conn.close()


def log_token_usage(
    paper_id: int,
    phase: str,
    input_tokens: int = 0,
    cache_read: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> None:
    """Append one token_usage row (append-only; never updated or deleted)."""
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO token_usage "
            "(paper_id, phase, input, cache_read, output, reasoning) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (paper_id, phase, input_tokens, cache_read, output_tokens, reasoning_tokens),
        )
        conn.commit()
    finally:
        conn.close()


def mark_paper_archived(paper_id: int) -> bool:
    """Move a paper to terminal state (``archive = 1``).

    This is the DB half of the LangGraph abort path: when the deterministic
    gate finds no extractable text layer, the abort node calls this instead
    of letting any agent run. Metadata stays NULL (nothing was extracted)
    and no ``Outputs/`` or ``questions`` rows are ever created, so
    ``archive = 1 AND paper_name IS NULL`` unambiguously means "aborted
    before extraction". Re-ingesting the same PDFs still raises
    :class:`DuplicatePaperError`, so an aborted pair can never loop back
    into Phase 1; OCR'd replacements hash differently and enter as new rows.

    Args:
        paper_id: Integer PK from pre-flight registration.

    Returns:
        True on success.

    Raises:
        ValueError: If ``paper_id`` does not exist.
    """
    init_db()
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE papers SET archive = 1 WHERE id = ?", (paper_id,)
        )
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"paper_id {paper_id} does not exist")
        return True
    finally:
        conn.close()


def register_paper(question_pdf_path: str, solution_pdf_path: str | None = None) -> int:
    """System pre-flight entry point (Python, NOT an AI tool).

    Call this exactly once per PDF pair BEFORE LangGraph starts:

    1. Compute the combined hash of the PDFs.
    2. If the hash already exists -> raise :class:`DuplicatePaperError`
       (the same set of PDFs must never go through Phase 1 again).
    3. Otherwise INSERT a stub row with the paths, the hash and
       ``archive = 0``; all metadata/boundary columns stay NULL for the
       Indexer agent to fill in later via UPDATE.
    4. Return the stable ``paper_id`` to put into LangGraph state.

    Args:
        question_pdf_path: Filesystem path to the questions PDF.
        solution_pdf_path: Filesystem path to the solutions PDF (or None).

    Returns:
        The integer primary key of the new papers row.

    Raises:
        DuplicatePaperError: If the PDF pair hash is already registered.
        FileNotFoundError: If a given PDF path does not exist.
    """
    init_db()
    pdf_hash = compute_paper_hash(question_pdf_path, solution_pdf_path)
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM papers WHERE pdf_hash = ?", (pdf_hash,)
        ).fetchone()
        if existing is not None:
            raise DuplicatePaperError(
                f"PDF pair already registered as paper_id={existing['id']}"
            )
        try:
            cur = conn.execute(
                """
                INSERT INTO papers
                    (question_pdf_path, solution_pdf_path, pdf_hash, archive)
                VALUES (?, ?, ?, 0)
                """,
                (question_pdf_path, solution_pdf_path, pdf_hash),
            )
        except sqlite3.IntegrityError:
            # Lost a race with a concurrent registration of the same pair.
            raise DuplicatePaperError(
                "PDF pair already registered (concurrent insert)"
            ) from None
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def update_paper_paths(
    paper_id: int,
    question_pdf_path: str | None,
    solution_pdf_path: str | None,
) -> None:
    """Point a paper row at relocated source PDFs (lifecycle moves).

    Raises ValueError for an unknown paper_id.
    """
    init_db()
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE papers SET question_pdf_path = ?, solution_pdf_path = ?"
            " WHERE id = ?",
            (question_pdf_path, solution_pdf_path, paper_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"paper_id {paper_id} does not exist")
    finally:
        conn.close()


def reset_stuck_running() -> list[int]:
    """Fail papers left mid-flight by a dead server restart; return their ids.

    A server restart kills background threads, so ``indexing``/``extracting``
    rows that survive a fresh boot can never complete. Failing them keeps the
    Processing page honest; re-running resumes normally.
    """
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM papers WHERE status IN ('indexing', 'extracting')"
        ).fetchall()
        ids = [int(r["id"]) for r in rows]
        if ids:
            conn.execute(
                "UPDATE papers SET status = 'failed', "
                "error = 'interrupted by server restart — re-run to resume' "
                "WHERE status IN ('indexing', 'extracting')"
            )
            conn.commit()
        return ids
    finally:
        conn.close()


def delete_paper(paper_id: int) -> bool:
    """Delete a paper row; its questions and token rows cascade.

    Returns True if a row was deleted, False if the id did not exist.
    (The Outputs/ folder is filesystem state -- remove it separately.)
    """
    init_db()
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
