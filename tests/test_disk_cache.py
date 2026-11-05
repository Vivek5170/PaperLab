"""Disk-cache endpoints: sizes + purge guards (backend only, no auth involved)."""
from __future__ import annotations

import directory_manager


def _seed(tmp_db, tmp_outputs, tmp_path, monkeypatch):
    import database as _db

    out = tmp_outputs
    cln = tmp_path / "cleaned"
    monkeypatch.setattr(directory_manager, "CLEANED_DIR", cln)
    dummy = tmp_path / "q.pdf"
    dummy.write_bytes(b"%PDF-1.4\n%EOF")
    sol = cln / "keep_solsplit.pdf"
    cln.mkdir(parents=True, exist_ok=True)
    sol.write_bytes(b"%PDF" + b"x" * 1000)
    conn = _db.get_connection()
    try:
        pid = conn.execute(
            "INSERT INTO papers (paper_name, status, question_pdf_path,"
            " solution_pdf_path) VALUES (?,?,?,?)",
            ("P", "done", str(dummy), str(sol))).lastrowid
        qid = conn.execute(
            "INSERT INTO questions (paper_id, question_number) VALUES (?, '1')",
            (pid,)).lastrowid
        conn.commit()
    finally:
        conn.close()
    qdir = directory_manager.get_question_dir(pid, "1") / "figures"
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "qfig1.png").write_bytes(b"\x89PNG" + b"f" * 500)   # must survive
    (qdir / "_question.png").write_bytes(b"\x89PNG" + b"r" * 2000)  # purgeable
    (qdir / "web_solution.png").write_bytes(b"\x89PNG" + b"w" * 1000)  # purgeable
    (cln / "drop_clean.pdf").write_bytes(b"%PDF" + b"d" * 3000)  # purgeable
    return pid


def test_disk_sizes_and_purge_guards(tmp_db, tmp_outputs, tmp_path, monkeypatch):
    from backend.routers import stats as st

    _seed(tmp_db, tmp_outputs, tmp_path, monkeypatch)
    usage = st.disk_usage()
    assert usage["renderCache"] == {"bytes": 3008, "files": 2}
    assert usage["cleanedPdfs"]["files"] == 1
    assert usage["cleanedPdfs"]["protected"] == 1
    assert usage["cleanedPdfs"]["bytes"] == 3004

    r = st.purge_render_cache()
    assert r == {"deleted": 2, "bytes": 3008}
    import directory_manager as dm

    left = [p.name for p in (dm.OUTPUT_BASE).rglob("*.png")]
    assert left == ["qfig1.png"], left

    c = st.purge_cleaned_pdfs()
    assert c["deleted"] == 1
    assert (dm.CLEANED_DIR / "keep_solsplit.pdf").is_file()  # DB-referenced kept
    assert not (dm.CLEANED_DIR / "drop_clean.pdf").exists()

    usage2 = st.disk_usage()
    assert usage2["renderCache"] == {"bytes": 0, "files": 0}
    assert usage2["cleanedPdfs"]["files"] == 0
