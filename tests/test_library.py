"""Library/reader helper tests (pure functions, no Streamlit)."""
from __future__ import annotations


def _row(pid, name=None, exam=None, status="done"):
    return {"id": pid, "paper_name": name, "exam_type": exam, "status": status}


def test_filter_papers_search_and_exam():
    from app.library import bucket_papers, exam_options, filter_papers

    rows = [_row(1, "GTA-01 Jee-Adv", "JEE Advanced"),
            _row(2, "NEET Mock 5", "NEET"),
            _row(3, None, None)]
    assert [r["id"] for r in filter_papers(rows, "gta")] == [1]
    assert [r["id"] for r in filter_papers(rows, "", "NEET")] == [2]
    assert [r["id"] for r in filter_papers(rows, "mock", "NEET")] == [2]
    assert filter_papers(rows, "zzz-no-match") == []
    assert exam_options(rows) == ["JEE Advanced", "NEET", "Unknown"]


def test_bucket_papers():
    from app.library import bucket_papers

    rows = [_row(1, status="uploaded"), _row(2, status="indexing"),
            _row(3, status="done"), _row(4, status="failed"),
            _row(5, status="extracting"), _row(6, status=None)]
    b = bucket_papers(rows)
    assert [r["id"] for r in b["queued"]] == [1, 6]
    assert [r["id"] for r in b["running"]] == [2, 5]
    assert [r["id"] for r in b["done"]] == [3]
    assert [r["id"] for r in b["failed"]] == [4]


def test_neighbor_ids():
    from app.reader import neighbor_ids, paper_title, question_ids

    rows = [{"question_number": n} for n in ("18", "19", "15-17_paragraph")]
    ids = question_ids(rows)
    assert neighbor_ids(ids, "19") == ("18", "15-17_paragraph")
    assert neighbor_ids(ids, "18") == (None, "19")
    assert neighbor_ids(ids, "15-17_paragraph") == ("19", None)
    assert neighbor_ids(ids, "bogus") == (None, "18")
    assert "GTA" in paper_title({"id": 3, "paper_name": "GTA", "exam_type": "JEE",
                                 "paper_date": "2024-01-01"})


def test_display_name_prefers_filename(tmp_db, tmp_path):
    import database
    from app.library import display_name

    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")
    pid = database.register_paper(str(q))
    row = database.get_paper(pid)
    assert display_name(row) == "q.pdf"  # unindexed: recognizable, not "unindexed"
    conn = database.get_connection()
    try:
        conn.execute("UPDATE papers SET paper_name='Titled' WHERE id = ?", (pid,))
        conn.commit()
    finally:
        conn.close()
    assert display_name(database.get_paper(pid)) == "Titled"


def test_delete_paper_cascades(tmp_db, tmp_path, tmp_outputs):
    import shutil

    import database
    import directory_manager

    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")
    pid = database.register_paper(str(q))
    database.log_token_usage(pid, "indexer", input_tokens=5)
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO questions (paper_id, question_number, latex_folder) "
            "VALUES (?, '1', 'x')", (pid,))
        conn.commit()
    finally:
        conn.close()
    (directory_manager.paper_dir(pid, tmp_outputs) / "1").mkdir(parents=True)
    assert database.delete_paper(pid) is True
    assert database.get_paper(pid) is None
    conn = database.get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) FROM questions WHERE paper_id = ?",
                         (pid,)).fetchone()[0]
        m = conn.execute("SELECT COUNT(*) FROM token_usage WHERE paper_id = ?",
                         (pid,)).fetchone()[0]
    finally:
        conn.close()
    assert (n, m) == (0, 0)
    shutil.rmtree(directory_manager.paper_dir(pid, tmp_outputs))
    assert database.delete_paper(pid) is False
