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


def _seed_archive(tmp_path, monkeypatch):
    import directory_manager as dm

    adir = tmp_path / "archive"
    adir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dm, "ARCHIVE_DIR", adir)
    return adir


def test_intermediates_purge_covers_crops(tmp_db, tmp_path, monkeypatch):
    import database as _db
    from backend.routers import stats as st

    adir = _seed_archive(tmp_path, monkeypatch)
    (adir / "a_QP_crop.pdf").write_bytes(b"%PDF" + b"c" * 500)
    keep_crop = adir / "b_QP_crop.pdf"
    keep_crop.write_bytes(b"%PDF" + b"k" * 700)
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO papers (paper_name, status, question_pdf_path,"
            " solution_pdf_path) VALUES (?,?,?,?)",
            ("P", "done", str(keep_crop), None))
        conn.commit()
    finally:
        conn.close()
    usage = st.disk_usage()
    assert usage["cropPdfs"]["files"] == 1  # referenced crop kept out
    assert usage["cropPdfs"]["protected"] == 1

    r = st.purge_intermediates()
    assert r["crop"] == 1
    assert r["deleted"] == 1
    assert not (adir / "a_QP_crop.pdf").exists()
    assert keep_crop.is_file()  # DB-referenced crop survives


def test_paper_pdfs_selective_delete(tmp_db, tmp_path, monkeypatch):
    import database as _db
    from backend.routers import stats as st

    adir = _seed_archive(tmp_path, monkeypatch)
    qp = adir / "GTA-99_QP.pdf"
    qp.write_bytes(b"%PDF" + b"q" * 100)
    sol = adir / "GTA-99_Key.pdf"
    sol.write_bytes(b"%PDF" + b"s" * 200)
    stray = adir / "notes_answer.pdf"
    stray.write_bytes(b"%PDF" + b"n" * 50)
    conn = _db.get_connection()
    try:
        pid = conn.execute(
            "INSERT INTO papers (paper_name, status, question_pdf_path,"
            " solution_pdf_path) VALUES (?,?,?,?)",
            ("P", "done", str(qp), str(sol))).lastrowid
        conn.commit()
    finally:
        conn.close()

    listing = st.paper_pdfs()
    paper = next((x for x in listing["papers"] if x["id"] == pid), None)
    assert paper is not None
    kinds = {f["kind"] for f in paper["files"]}
    assert kinds == {"question", "solution"}
    assert all(f["exists"] for f in paper["files"])
    assert {u["name"] for u in listing["unlinked"]} == {"notes_answer.pdf"}

    # Outside-data paths are refused, never deleted.
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-out")
    bad = st.delete_paper_pdfs({"paths": [str(outside)], "unlinked": []})
    assert bad["deleted"] == 0
    assert bad["refused"] != []
    assert outside.is_file()

    res = st.delete_paper_pdfs({"paths": [str(sol)], "unlinked": []})
    assert res["deleted"] == 1
    assert not sol.exists() and qp.is_file()
    conn = _db.get_connection()
    try:
        row = conn.execute(
            "SELECT question_pdf_path, solution_pdf_path FROM papers"
            " WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    assert row[0] == str(qp) and row[1] is None

    res2 = st.delete_paper_pdfs(
        {"paths": [], "unlinked": [{"location": "archive", "name": stray.name}]})
    assert res2["deleted"] == 1
    assert not stray.exists()
