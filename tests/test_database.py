"""Database tests: schema, defaults, unique hash, foreign keys, pre-flight hash."""
from __future__ import annotations

import sqlite3

import pytest

import database


def test_tables_created_with_required_columns(tmp_db):
    conn = database.get_connection()
    try:
        papers = {r["name"] for r in conn.execute("PRAGMA table_info(papers)")}
        questions = {r["name"] for r in conn.execute("PRAGMA table_info(questions)")}
    finally:
        conn.close()
    for col in ("id", "paper_name", "exam_type", "paper_date", "source_institute",
                "question_pdf_path", "solution_pdf_path", "pdf_hash", "archive"):
        assert col in papers, f"papers missing column {col}"
    for col in ("id", "paper_id", "question_number", "latex_folder", "status"):
        assert col in questions, f"questions missing column {col}"


def test_question_number_is_text_type(tmp_db):
    conn = database.get_connection()
    try:
        cols = {r["name"]: r["type"] for r in conn.execute("PRAGMA table_info(questions)")}
    finally:
        conn.close()
    assert cols["question_number"].upper() == "TEXT"


def test_unique_hash_constraint(tmp_db):
    conn = database.get_connection()
    try:
        conn.execute("INSERT INTO papers (paper_name, pdf_hash) VALUES ('A', 'abc123')")
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO papers (paper_name, pdf_hash) VALUES ('B', 'abc123')")
            conn.commit()
    finally:
        conn.close()


def test_foreign_key_constraint_enforced(tmp_db):
    conn = database.get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO questions (paper_id, question_number) VALUES (9999, '1')"
            )
            conn.commit()
    finally:
        conn.close()


def test_defaults_archive_and_status(tmp_db):
    conn = database.get_connection()
    try:
        cur = conn.execute("INSERT INTO papers (paper_name, pdf_hash) VALUES ('P', 'h1')")
        pid = cur.lastrowid
        conn.execute(
            "INSERT INTO questions (paper_id, question_number) VALUES (?, '15a')", (pid,)
        )
        conn.commit()
        paper = conn.execute("SELECT archive FROM papers WHERE id = ?", (pid,)).fetchone()
        q = conn.execute(
            "SELECT status FROM questions WHERE paper_id = ?", (pid,)
        ).fetchone()
    finally:
        conn.close()
    assert paper["archive"] == 0
    assert q["status"] == "draft"


def test_register_paper_creates_stub_row(tmp_db, tmp_path):
    q = tmp_path / "q.pdf"
    s = tmp_path / "s.pdf"
    q.write_bytes(b"question-bytes")
    s.write_bytes(b"solution-bytes")
    pid = database.register_paper(str(q), str(s))
    assert isinstance(pid, int) and pid > 0
    row = database.get_paper(pid)
    assert row is not None
    assert row["question_pdf_path"] == str(q)
    assert row["solution_pdf_path"] == str(s)
    assert row["archive"] == 0
    # Metadata columns stay NULL for the Indexer agent to fill in.
    assert row["paper_name"] is None
    assert row["q_start"] is None
    expected = database.compute_paper_hash(str(q), str(s))
    assert row["pdf_hash"] == expected


def test_register_paper_duplicate_pair_aborts(tmp_db, tmp_path):
    q = tmp_path / "q.pdf"
    s = tmp_path / "s.pdf"
    q.write_bytes(b"qq")
    s.write_bytes(b"ss")
    pid = database.register_paper(str(q), str(s))
    assert pid > 0
    with pytest.raises(database.DuplicatePaperError):
        database.register_paper(str(q), str(s))


def test_register_paper_without_solution_pdf(tmp_db, tmp_path):
    q = tmp_path / "only_q.pdf"
    q.write_bytes(b"lonely questions")
    pid = database.register_paper(str(q))
    row = database.get_paper(pid)
    assert row is not None and row["solution_pdf_path"] is None
    assert row["pdf_hash"] == database.compute_paper_hash(str(q))
    # Same question PDF + a solution PDF is a different pair -> allowed.
    s = tmp_path / "s.pdf"
    s.write_bytes(b"solutions")
    pid2 = database.register_paper(str(q), str(s))
    assert pid2 != pid


def test_compute_paper_hash_stable_and_order_sensitive(tmp_path):
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"AAA")
    b.write_bytes(b"BBB")
    assert database.compute_paper_hash(str(a), str(b)) == database.compute_paper_hash(
        str(a), str(b)
    )
    assert database.compute_paper_hash(str(a), str(b)) != database.compute_paper_hash(
        str(b), str(a)
    )


def test_grouped_question_numbers_stored_verbatim(tmp_db):
    conn = database.get_connection()
    try:
        cur = conn.execute("INSERT INTO papers (paper_name, pdf_hash) VALUES ('P', 'hh')")
        pid = cur.lastrowid
        for qn in ("15-17_paragraph", "15a"):
            conn.execute(
                "INSERT INTO questions (paper_id, question_number) VALUES (?, ?)",
                (pid, qn),
            )
        conn.commit()
        rows = conn.execute(
            "SELECT question_number FROM questions WHERE paper_id = ? ORDER BY id", (pid,)
        ).fetchall()
    finally:
        conn.close()
    assert [r["question_number"] for r in rows] == ["15-17_paragraph", "15a"]


def test_mark_paper_archived_abort_path(tmp_db, tmp_path):
    """Abort path: archive flips to 1, metadata stays NULL, no side rows."""
    q = tmp_path / "q.pdf"
    s = tmp_path / "s.pdf"
    q.write_bytes(b"qq")
    s.write_bytes(b"ss")
    pid = database.register_paper(str(q), str(s))
    assert database.mark_paper_archived(pid) is True
    row = database.get_paper(pid)
    assert row["archive"] == 1
    assert row["paper_name"] is None and row["q_start"] is None
    conn = database.get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM questions WHERE paper_id = ?", (pid,)
        ).fetchone()["c"]
    finally:
        conn.close()
    assert n == 0
    # Same pair still aborts as duplicate -- aborted papers never re-enter.
    with pytest.raises(database.DuplicatePaperError):
        database.register_paper(str(q), str(s))


def test_mark_paper_archived_unknown_id_fails(tmp_db):
    with pytest.raises(ValueError):
        database.mark_paper_archived(99999)
