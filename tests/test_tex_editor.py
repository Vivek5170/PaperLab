"""TeX editor endpoints: GET raw tex / POST draft preview / PATCH save."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import database
import directory_manager
from backend.deps import require_admin
from backend.main import app

VALID_TEX = "Find $x^2$ for \\textbf{body}."
UPDATED_TEX = "Find $x^3$ for \\textbf{body}."
INVALID_TEX = "Unclosed \\frac{x"


@pytest.fixture()
def tex_client(tmp_db, tmp_outputs):
    database.init_topics()
    dummy = tmp_db.parent / "dummy.pdf"
    dummy.write_bytes(b"%PDF-1.4\n%EOF")
    conn = database.get_connection()
    try:
        pid = conn.execute(
            "INSERT INTO papers (paper_name, exam_type, paper_date,"
            " source_institute, status, question_pdf_path) VALUES (?,?,?,?,?,?)",
            ("Paper T", "JEE Main", "2024-01-01", "Test", "done", str(dummy)),
        ).lastrowid
        conn.execute(
            "INSERT INTO questions (paper_id, question_number, qtype,"
            " difficulty, status) VALUES (?,?,?,?,?)",
            (pid, "1", "scq", "Easy", "draft"),
        )
        conn.commit()
    finally:
        conn.close()
    qdir = directory_manager.get_question_dir(pid, "1")
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "question.tex").write_text(VALID_TEX, encoding="utf-8")
    (qdir / "solution.tex").write_text("Solution $y$.", encoding="utf-8")
    app.dependency_overrides[require_admin] = lambda: None
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, pid
    finally:
        app.dependency_overrides.pop(require_admin, None)


def _tex_url(pid, qn="1", part="question"):
    return f"/api/papers/{pid}/questions/{qn}/tex?part={part}"


def test_get_tex_round_trip(tex_client):
    client, pid = tex_client
    r = client.get(_tex_url(pid))
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["tex"] == VALID_TEX
    assert body["fileName"] == "question.tex"
    assert len(body["sha256"]) == 64


def test_get_tex_rejects_bad_part_and_missing(tex_client):
    client, pid = tex_client
    assert client.get(_tex_url(pid, part="bogus")).status_code == 400
    assert client.get(_tex_url(pid, qn="nope")).status_code == 404


def test_tex_routes_require_admin(tmp_db, tmp_outputs):
    # No dependency override: session cookie missing -> 401.
    from backend.main import app as _app

    _app.dependency_overrides.pop(require_admin, None)
    with TestClient(_app, raise_server_exceptions=False) as client:
        assert client.get("/api/papers/1/questions/1/tex?part=question").status_code == 401
        assert client.post("/api/papers/1/questions/1/tex/preview",
                           json={"tex": "x"}).status_code == 401


def test_preview_matches_reader_and_writes_nothing(tex_client):
    client, pid = tex_client
    qdir = directory_manager.get_question_dir(pid, "1")
    before = (qdir / "question.tex").read_bytes()
    r = client.post(f"/api/papers/{pid}/questions/1/tex/preview",
                    json={"tex": "Find $x^2$.", "part": "question"})
    assert r.status_code == 200, r.text[:300]
    segs = r.json()["segments"]
    assert segs and segs[0]["kind"] == "text"
    assert "x%5E2" in segs[0]["html"]  # math lives URL-encoded in data-tex
    # Read-only: no backup files, source untouched.
    assert (qdir / "question.tex").read_bytes() == before
    assert list(qdir.glob("*.bak-*")) == []
    # Bad part rejected.
    assert client.post(f"/api/papers/{pid}/questions/1/tex/preview",
                       json={"tex": "x", "part": "bogus"}).status_code == 400


def test_save_validates_writes_backup_and_returns_segments(tex_client):
    client, pid = tex_client
    qdir = directory_manager.get_question_dir(pid, "1")
    sha = client.get(_tex_url(pid)).json()["sha256"]
    # Invalid LaTeX: rejected, file + no backup.
    r = client.patch(f"/api/papers/{pid}/questions/1/tex",
                     json={"part": "question", "tex": INVALID_TEX, "expectedSha": sha})
    assert r.status_code == 400
    assert (qdir / "question.tex").read_text(encoding="utf-8") == VALID_TEX
    assert list(qdir.glob("*.bak-*")) == []
    # Valid save: bytes written, backup kept, segments returned.
    r = client.patch(f"/api/papers/{pid}/questions/1/tex",
                     json={"part": "question", "tex": UPDATED_TEX, "expectedSha": sha})
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["saved"] is True
    assert (qdir / "question.tex").read_text(encoding="utf-8") == UPDATED_TEX
    backups = list(qdir.glob("question.tex.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == VALID_TEX
    assert "x%5E3" in body["segments"][0]["html"]
    # Stale sha: concurrent-save guard.
    r = client.patch(f"/api/papers/{pid}/questions/1/tex",
                     json={"part": "question", "tex": "Other $z$.", "expectedSha": sha})
    assert r.status_code == 409
    assert (qdir / "question.tex").read_text(encoding="utf-8") == UPDATED_TEX
