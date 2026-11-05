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
    sol_section_start INTEGER,
    sections TEXT,
    status TEXT DEFAULT 'uploaded',
    error TEXT,
    elapsed_sec REAL
);
"""

SCHEMA_TOPICS = """
CREATE TABLE IF NOT EXISTS topics (
    code TEXT PRIMARY KEY,
    parent TEXT,
    level TEXT NOT NULL CHECK (level IN ('module','chapter','week','subtopic')),
    name TEXT NOT NULL,
    descr TEXT NOT NULL DEFAULT '',
    rev INTEGER NOT NULL DEFAULT 1
);
"""

SCHEMA_QUESTION_TOPICS = """
CREATE TABLE IF NOT EXISTS question_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    topic_code TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 0,
    src TEXT NOT NULL DEFAULT 'human'
        CHECK (src IN ('auto','human')),
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    FOREIGN KEY (topic_code) REFERENCES topics(code),
    UNIQUE (question_id, topic_code)
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

# Allowed per-question format types (Node 2, section-first).
# Base: scq single-correct, msq multi-correct, int integer 0-9,
# num decimal/numeric, mtx match-table. par-* = passage group with
# uniform sub-format, par-mix = mixed subs, unknown = explicit fallback.
QTYPE_VALUES = (
    "scq", "msq", "int", "num", "mtx",
    "par-scq", "par-msq", "par-int", "par-num", "par-mtx", "par-mix",
    "unknown",
)

DIFFICULTY_VALUES = ("Easy", "Medium", "Hard")

TOPIC_SEED_FILE = Path(__file__).parent / "topics_seed.json"

SCHEMA_QUESTIONS = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL,
    question_number TEXT NOT NULL,
    latex_folder TEXT,
    status TEXT DEFAULT 'draft',
    qtype TEXT NOT NULL DEFAULT 'unknown'
        CHECK (qtype IN ('scq','msq','int','num','mtx','par-scq','par-msq','par-int','par-num','par-mtx','par-mix','unknown')),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    UNIQUE (paper_id, question_number)
);
"""

# Indexes backing the /api/search endpoint. Created lazily inside init_db
# (migration-safe IF NOT EXISTS) so existing databases gain them on next
# boot; sized for ~20k questions (B-tree lookups + GROUP BY, no full scans).
SEARCH_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_questions_paper ON questions(paper_id)",
    "CREATE INDEX IF NOT EXISTS idx_questions_qtype ON questions(qtype)",
    "CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty)",
    "CREATE INDEX IF NOT EXISTS idx_papers_exam ON papers(exam_type)",
    "CREATE INDEX IF NOT EXISTS idx_papers_institute ON papers(source_institute)",
    "CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status)",
    "CREATE INDEX IF NOT EXISTS idx_qt_qid ON question_topics(question_id)",
    "CREATE INDEX IF NOT EXISTS idx_qt_topic ON question_topics(topic_code)",
    "CREATE INDEX IF NOT EXISTS idx_topics_parent ON topics(parent)",
)


def _ensure_search_indexes(conn: sqlite3.Connection) -> None:
    """Create /api/search indexes; safe to re-run on every init_db.

    Column-aware: pre-migration tables (see
    test_migrate_old_db_gets_status_and_token_table) may lack newer
    columns, so only index what exists. Later init_db runs pick up the
    rest once migrations add the columns.
    """
    cols: dict[str, set[str]] = {}
    for stmt in SEARCH_INDEXES:
        # "CREATE INDEX IF NOT EXISTS <name> ON <table>(<column>)"
        try:
            rest = stmt.split(" ON ", 1)[1]
            table, col = rest.split("(", 1)
            table, col = table.strip(), col.rstrip(")").strip()
        except (IndexError, ValueError):
            continue
        if table not in cols:
            cols[table] = {r["name"] for r in
                           conn.execute(f"PRAGMA table_info({table})").fetchall()} \
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table'"
                    " AND name = ?", (table,)).fetchone() else set()
        if col in cols[table]:
            conn.execute(stmt)


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Return a SQLite connection with foreign keys enforced (WAL for readers)."""
    path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except sqlite3.Error:
        pass
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
        conn.execute(SCHEMA_TOPICS)
        conn.execute(SCHEMA_QUESTION_TOPICS)
        qcols = {r["name"] for r in conn.execute("PRAGMA table_info(questions)")}
        if "qtype" not in qcols:
            conn.execute(
                "ALTER TABLE questions ADD COLUMN qtype TEXT NOT NULL DEFAULT 'unknown'"
            )
            qcols.add("qtype")
        tcols = {r["name"] for r in conn.execute("PRAGMA table_info(topics)")}
        if "rev" not in tcols:
            conn.execute(
                "ALTER TABLE topics ADD COLUMN rev INTEGER NOT NULL DEFAULT 1"
            )
            tcols.add("rev")
        if "slug" in tcols:
            # Slugs were dropped: agents answer by list index, humans by
            # path. Raw codes stay internal IDs.
            conn.execute("DROP INDEX IF EXISTS idx_topics_slug")
            conn.execute("ALTER TABLE topics DROP COLUMN slug")
            tcols.discard("slug")
        if "difficulty" not in qcols:
            conn.execute(
                "ALTER TABLE questions ADD COLUMN difficulty TEXT "
                "CHECK (difficulty IN ('Easy','Medium','Hard'))"
            )
            qcols.add("difficulty")
        if "topic_suggestion" not in qcols:
            conn.execute("ALTER TABLE questions ADD COLUMN topic_suggestion TEXT")
            qcols.add("topic_suggestion")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(papers)")}
        if "sections" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN sections TEXT")
            cols.add("sections")
        if "status" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN status TEXT DEFAULT 'uploaded'")
        if "error" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN error TEXT")
        if "elapsed_sec" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN elapsed_sec REAL")
        if "sol_section_start" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN sol_section_start INTEGER")
            cols.add("sol_section_start")
        # Backfill indexed rows: separate PDFs started their section at p.1,
        # questions-only papers get 0. Unindexed rows stay NULL. Same-path
        # (combined) rows are left NULL -- their split point is unknown and
        # must come from a re-index, never guessed as 1. Guarded for
        # pre-boundary DBs that lack q_start/s_start entirely.
        if {"q_start", "s_start", "sol_section_start"} <= cols:
            has_paths = {"question_pdf_path", "solution_pdf_path"} <= cols
            same_path = (
                "AND solution_pdf_path IS NOT NULL "
                "AND question_pdf_path IS NOT solution_pdf_path"
                if has_paths else ""
            )
            conn.execute(
                "UPDATE papers SET sol_section_start = 1 "
                "WHERE q_start IS NOT NULL AND s_start IS NOT NULL "
                f"AND sol_section_start IS NULL {same_path}"
            )
            conn.execute(
                "UPDATE papers SET sol_section_start = 0 "
                "WHERE q_start IS NOT NULL AND s_start IS NULL "
                "AND sol_section_start IS NULL"
            )
        _ensure_search_indexes(conn)
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
    if solution_pdf_path is None or os.path.realpath(
        solution_pdf_path
    ) == os.path.realpath(question_pdf_path):
        # Combined flow (same file chosen as its own solution): hash once.
        # realpath (not plain string compare) so "./q.pdf" vs "q.pdf"
        # still dedups to one row.
        paths = (question_pdf_path,)
    else:
        paths = (question_pdf_path, solution_pdf_path)
    for path in paths:
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


def init_topics(db_path: str | Path | None = None) -> int:
    """Seed the topics tree from topics_seed.json (once; no-op when filled).

    Returns the number of topic rows present afterwards.
    """
    import json

    init_db(db_path)
    conn = get_connection(db_path)
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM topics").fetchone()["c"]
        if n == 0:
            seed = json.loads(TOPIC_SEED_FILE.read_text(encoding="utf-8"))
            for node in seed["nodes"]:
                conn.execute(
                    "INSERT INTO topics (code, parent, level, name, descr)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (node["code"], node["parent"], node["level"],
                     node["name"], node.get("descr", "")),
                )
            conn.commit()
        n = conn.execute("SELECT COUNT(*) AS c FROM topics").fetchone()["c"]
        return int(n)
    finally:
        conn.close()


def topic_path(code: str, db_path: str | Path | None = None) -> str:
    """Breadcrumb 'Module › Chapter › Week › Subtopic' for one topic code."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        by_code = {r["code"]: r for r in conn.execute(
            "SELECT code, parent, name FROM topics").fetchall()}
    finally:
        conn.close()
    if code not in by_code:
        raise ValueError(f"unknown topic code {code!r}")
    parts, cur = [], code
    while cur is not None:
        node = by_code.get(cur)
        if node is None:
            break
        parts.append(node["name"])
        cur = node["parent"]
    return " › ".join(reversed(parts))


def resolve_topic(ref: str, db_path: str | Path | None = None) -> str:
    """Map a code, exact name, or full '›' path to one topic code.

    Raw EJEE codes stay internal IDs; callers (agent list indices resolve
    to these before calling) never need to invent one. Ambiguous or
    unknown refs raise ValueError listing the candidates, so a guess is
    never stored silently.
    """
    ref = str(ref or "").strip()
    if not ref:
        raise ValueError("empty topic reference")
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT code, parent, name FROM topics").fetchall()
    finally:
        conn.close()
    by_code = {r["code"]: r for r in rows}
    if ref in by_code:
        return ref
    low = ref.lower()
    names = [r["code"] for r in rows if r["name"].lower() == low]
    if len(names) == 1:
        return names[0]
    candidates = names
    if len(candidates) != 1:
        # Last resort: match against full breadcrumb paths.
        paths = {}
        for r in rows:
            parts, cur = [], r["code"]
            while cur is not None and cur in by_code:
                parts.append(by_code[cur]["name"])
                cur = by_code[cur]["parent"]
            paths[r["code"]] = " › ".join(reversed(parts)).lower()
        hits = [c for c, p in paths.items() if p == low]
        candidates = hits or [c for c, p in paths.items() if low in p][:8]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        f"ambiguous/unknown topic {ref!r}: candidates {candidates or 'none'}"
    )


def set_question_topics(
    question_id: int, refs: list[str], src: str = "human"
) -> int:
    """Replace one question's topic links of the given source.

    Refs may be codes, slugs, names, or full paths (resolved via
    resolve_topic); raw codes are never required from callers.
    src='auto' replaces only auto rows (human picks are never touched);
    src='human' replaces everything. Bad refs raise ValueError.
    Returns the number of links written.
    """
    if src not in ("auto", "human"):
        raise ValueError(f"src must be 'auto' or 'human', got {src!r}")
    codes = [resolve_topic(r) for r in refs]
    init_db()
    conn = get_connection()
    try:
        if conn.execute(
            "SELECT id FROM questions WHERE id = ?", (question_id,)
        ).fetchone() is None:
            raise ValueError(f"question id {question_id} does not exist")
        if src == "auto":
            conn.execute(
                "DELETE FROM question_topics WHERE question_id = ? AND src = 'auto'",
                (question_id,),
            )
        else:
            conn.execute(
                "DELETE FROM question_topics WHERE question_id = ?", (question_id,))
        for rank, code in enumerate(codes):
            conn.execute(
                "INSERT INTO question_topics (question_id, topic_code, rank, src)"
                " VALUES (?, ?, ?, ?)",
                (question_id, code, rank, src),
            )
        conn.commit()
        return len(codes)
    finally:
        conn.close()


def set_question_difficulty(
    paper_id: int,
    question_number: str,
    difficulty: str | None,
    topic_suggestion: str | None = None,
    only_fill: bool = False,
) -> bool:
    """Set difficulty (Easy/Medium/Hard or None to clear) + suggestion text.

    An empty suggestion clears the column to NULL. With only_fill=True
    (Node 3 auto), a parsed difficulty fills only a NULL column -- a
    human grade is never overwritten -- and a NULL parse writes nothing.
    Raises ValueError for a bad difficulty or unknown question.
    """
    if difficulty is not None and difficulty not in DIFFICULTY_VALUES:
        raise ValueError(
            f"bad difficulty {difficulty!r}: must be one of {', '.join(DIFFICULTY_VALUES)}"
        )
    init_db()
    conn = get_connection()
    try:
        if only_fill:
            cur_row = conn.execute(
                "SELECT difficulty FROM questions"
                " WHERE paper_id = ? AND question_number = ?",
                (paper_id, str(question_number)),
            ).fetchone()
            if cur_row is None:
                raise ValueError(
                    f"no question {question_number!r} in paper_id {paper_id}"
                )
            if cur_row["difficulty"] is not None:
                difficulty = cur_row["difficulty"]  # human grade wins
            if difficulty is None and topic_suggestion is None:
                return True  # parse produced nothing storable
        if topic_suggestion is None:
            cur = conn.execute(
                "UPDATE questions SET difficulty = ?"
                " WHERE paper_id = ? AND question_number = ?",
                (difficulty, paper_id, str(question_number)),
            )
        else:
            cur = conn.execute(
                "UPDATE questions SET difficulty = ?, topic_suggestion = ?"
                " WHERE paper_id = ? AND question_number = ?",
                (difficulty, topic_suggestion or None,
                 paper_id, str(question_number)),
            )
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(
                f"no question {question_number!r} in paper_id {paper_id}"
            )
        return True
    finally:
        conn.close()


def get_question_id(paper_id: int, question_number: str) -> int:
    """questions.id for a (paper, number) pair; ValueError when absent."""
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM questions WHERE paper_id = ? AND question_number = ?",
            (paper_id, str(question_number)),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(
            f"no question {question_number!r} in paper_id {paper_id}"
        )
    return int(row["id"])


def get_question_links(question_id: int) -> list[tuple]:
    """[(topic_code, rank, src)] for one question, primary first."""
    init_db()
    conn = get_connection()
    try:
        return [(r["topic_code"], r["rank"], r["src"]) for r in conn.execute(
            "SELECT topic_code, rank, src FROM question_topics "
            "WHERE question_id = ? ORDER BY rank, topic_code",
            (question_id,)).fetchall()]
    finally:
        conn.close()


def topic_options(levels: tuple = ("subtopic",)) -> list[tuple]:
    """[(code, breadcrumb path, level)] for pickers (cached by caller).

    Defaults to subtopics only: questions are tagged at subtopic level,
    so modules/chapters/weeks must never be selectable as topics.
    """
    init_db()
    conn = get_connection()
    try:
        all_rows = conn.execute(
            "SELECT code, parent, level, name FROM topics").fetchall()
    finally:
        conn.close()
    by_code = {r["code"]: r for r in all_rows}
    out = []
    for r in all_rows:
        if r["level"] not in levels:
            continue
        parts, cur = [], r["code"]
        while cur is not None and cur in by_code:
            parts.append(by_code[cur]["name"])
            cur = by_code[cur]["parent"]
        out.append((r["code"], " › ".join(reversed(parts)), r["level"]))
    return out


def get_topic(code: str, db_path: str | Path | None = None):
    """One topic row as a dict; None when absent."""
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT code, parent, level, name, descr, rev FROM topics "
            "WHERE code = ?", (str(code),)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def update_topic(code: str, name: str, descr: str, expected_rev: int) -> int:
    """Rename/edit a topic; optimistic locking via expected_rev.

    Returns the new rev. Raises ValueError on stale rev (someone saved
    first) or unknown code. Name must be non-empty.
    """
    name = str(name or "").strip()
    if not name:
        raise ValueError("topic name must not be empty")
    init_db()
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE topics SET name = ?, descr = ?, rev = rev + 1"
            " WHERE code = ? AND rev = ?",
            (name, str(descr or ""), str(code), int(expected_rev)),
        )
        conn.commit()
        if cur.rowcount == 0:
            if get_topic(code) is None:
                raise ValueError(f"unknown topic code {code!r}")
            raise ValueError(
                f"{code} changed by someone else (rev moved) -- reload and retry"
            )
        return int(conn.execute(
            "SELECT rev FROM topics WHERE code = ?", (str(code),)).fetchone()["rev"])
    finally:
        conn.close()


def add_module(name: str) -> str:
    """Add a top-level module (next free M number). Returns the new code."""
    name = str(name or "").strip()
    if not name:
        raise ValueError("module name must not be empty")
    import re as _re
    init_db()
    conn = get_connection()
    try:
        nums = [int(m.group(1)) for r in conn.execute(
            "SELECT code FROM topics WHERE level = 'module'").fetchall()
            for m in [_re.match(r"^M(\d+)$", r["code"])] if m]
        code = f"M{max(nums, default=0) + 1}"
        conn.execute(
            "INSERT INTO topics (code, parent, level, name, descr)"
            " VALUES (?, NULL, 'module', ?, '')",
            (code, name),
        )
        conn.commit()
        return code
    finally:
        conn.close()


def add_topic(parent_code: str, level: str, name: str, descr: str = "") -> str:
    """Add a child node; the code is generated, never typed.

    Chapters go under modules (next free PH number), weeks under
    chapters (next Wn), subtopics under weeks (next NN in chapter).
    Returns the new code.
    """
    name = str(name or "").strip()
    if not name:
        raise ValueError("topic name must not be empty")
    if level not in ("chapter", "week", "subtopic"):
        raise ValueError(f"level must be chapter/week/subtopic, got {level!r}")
    init_db()
    conn = get_connection()
    try:
        parent = conn.execute(
            "SELECT code, level FROM topics WHERE code = ?",
            (str(parent_code),)).fetchone()
        if parent is None:
            raise ValueError(f"unknown parent {parent_code!r}")
        import re as _re
        if level == "chapter":
            if parent["level"] != "module":
                raise ValueError("chapters go under modules")
            nums = [int(m.group(1)) for r in conn.execute(
                "SELECT code FROM topics WHERE level = 'chapter'").fetchall()
                for m in [_re.match(r"^PH(\d+)$", r["code"])] if m]
            code = f"PH{max(nums, default=0) + 1:02d}"
        elif level == "week":
            if parent["level"] != "chapter":
                raise ValueError("weeks go under chapters")
            chap = parent["code"]
            nums = [int(m.group(1)) for r in conn.execute(
                "SELECT code FROM topics WHERE parent = ?", (chap,)).fetchall()
                for m in [_re.match(r".*-W(\d+)$", r["code"])] if m]
            code = f"{chap}-W{max(nums, default=0) + 1}"
        else:
            if parent["level"] != "week":
                raise ValueError("subtopics go under weeks")
            chap = parent["code"].split("-")[0]
            nums = [int(m.group(1)) for r in conn.execute(
                "SELECT code FROM topics WHERE code LIKE ?",
                (f"{chap}.%",)).fetchall()
                for m in [_re.match(r"^PH\d+\.(\d+)$", r["code"])] if m]
            code = f"{chap}.{max(nums, default=0) + 1:02d}"
        conn.execute(
            "INSERT INTO topics (code, parent, level, name, descr)"
            " VALUES (?, ?, ?, ?, ?)",
            (code, parent["code"], level, name, str(descr or "")),
        )
        conn.commit()
        return code
    finally:
        conn.close()


def move_topic(code: str, new_parent: str) -> bool:
    """Reparent a node without breaking code semantics.

    Subtopics stay within their chapter (week to week), weeks stay
    within their chapter, chapters may move across modules. Anything
    else raises ValueError.
    """
    init_db()
    conn = get_connection()
    try:
        node = conn.execute(
            "SELECT code, parent, level FROM topics WHERE code = ?",
            (str(code),)).fetchone()
        dest = conn.execute(
            "SELECT code, level FROM topics WHERE code = ?",
            (str(new_parent),)).fetchone()
        if node is None:
            raise ValueError(f"unknown topic {code!r}")
        if dest is None:
            raise ValueError(f"unknown destination {new_parent!r}")
        lvl, want = node["level"], None
        if lvl == "subtopic":
            want = ("week", node["code"].split(".")[0])
            if dest["level"] != "week" or not dest["code"].startswith(want[1] + "-"):
                raise ValueError(
                    "subtopics move week-to-week within their chapter only")
        elif lvl == "week":
            want_chap = node["code"].split("-")[0]
            if dest["level"] != "chapter" or dest["code"] != want_chap:
                raise ValueError("weeks stay within their chapter")
        elif lvl == "chapter":
            if dest["level"] != "module":
                raise ValueError("chapters move module-to-module only")
        else:
            raise ValueError("modules cannot be moved")
        conn.execute("UPDATE topics SET parent = ?, rev = rev + 1 WHERE code = ?",
                     (dest["code"], node["code"]))
        conn.commit()
        return True
    finally:
        conn.close()


def delete_topic(code: str) -> bool:
    """Delete a leaf topic with zero question links.

    Refuses (ValueError) when children or question links exist -- reassign
    them first. Returns True on success.
    """
    init_db()
    conn = get_connection()
    try:
        if conn.execute("SELECT code FROM topics WHERE code = ?",
                        (str(code),)).fetchone() is None:
            raise ValueError(f"unknown topic {code!r}")
        kids = conn.execute("SELECT COUNT(*) AS c FROM topics WHERE parent = ?",
                            (str(code),)).fetchone()["c"]
        if kids:
            raise ValueError(f"{code} has {kids} child node(s) -- move them first")
        used = conn.execute(
            "SELECT COUNT(*) AS c FROM question_topics WHERE topic_code = ?",
            (str(code),)).fetchone()["c"]
        if used:
            raise ValueError(
                f"{code} tags {used} question(s) -- retag them first")
        conn.execute("DELETE FROM topics WHERE code = ?", (str(code),))
        conn.commit()
        return True
    finally:
        conn.close()


def set_question_qtype(paper_id: int, question_number: str, qtype: str) -> bool:
    """Correct one question's format type (Streamlit correction control).

    Validated against QTYPE_VALUES; raises ValueError for a bad type or
    an unknown (paper_id, question_number). Returns True on success.
    """
    qt = str(qtype or "").strip().lower()
    if qt not in QTYPE_VALUES:
        raise ValueError(
            f"bad qtype {qtype!r}: must be one of {', '.join(QTYPE_VALUES)}"
        )
    init_db()
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE questions SET qtype = ? WHERE paper_id = ? AND question_number = ?",
            (qt, paper_id, str(question_number)),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(
                f"no question {question_number!r} in paper_id {paper_id}"
            )
        return True
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
