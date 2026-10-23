"""Submission + LaTeX verification tests (corrected pipeline flow).

Flow under test: Python pre-flight ``database.register_paper`` creates the
stub row and returns ``paper_id`` -> Indexer agent fills it in via the
``submit_metadata_and_boundaries`` UPDATE tool -> Extractor submits
questions/solutions. ``paper_id`` always originates from pre-flight, never
from the agent.
"""
from __future__ import annotations

import pytest

import database
import directory_manager as dm
from tools_extractor import submit_question, submit_solution, verify_latex_syntax
from tools_indexer import submit_metadata_and_boundaries

_META = {
    "paper_name": "JEE Advanced 2024 Paper 1",
    "exam_type": "JEE",
    "paper_date": "2024-05-26",
    "source_institute": "IIT Madras",
    "q_start": 1,
    "q_end": 5,
    "s_start": 6,
    "s_end": 10,
}


def _paper_id(tmp_db, tmp_path, tag="p"):
    """Simulate system pre-flight: register stub row, return its paper_id."""
    q = tmp_path / f"{tag}_q.pdf"
    s = tmp_path / f"{tag}_s.pdf"
    q.write_bytes(f"questions-{tag}".encode())
    s.write_bytes(f"solutions-{tag}".encode())
    return database.register_paper(str(q), str(s))


def _submit_meta(pid):
    return submit_metadata_and_boundaries.invoke({"paper_id": pid, **_META})


def test_submit_metadata_updates_preregistered_row(tmp_db, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    # Stub row: paths + hash present, metadata NULL.
    stub = database.get_paper(pid)
    assert stub is not None and stub["paper_name"] is None
    assert stub["archive"] == 0

    assert _submit_meta(pid) is True
    conn = database.get_connection()
    try:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    assert row["paper_name"] == "JEE Advanced 2024 Paper 1"
    assert (row["q_start"], row["q_end"], row["s_start"], row["s_end"]) == (1, 5, 6, 10)
    # Pre-flight columns untouched by the agent UPDATE.
    assert row["question_pdf_path"] == stub["question_pdf_path"]
    assert row["pdf_hash"] == stub["pdf_hash"]


def test_submit_metadata_recall_overwrites(tmp_db, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    _submit_meta(pid)
    out = submit_metadata_and_boundaries.invoke({"paper_id": pid, **{**_META, "q_end": 7}})
    assert out is True
    assert database.get_paper(pid)["q_end"] == 7


def test_submit_metadata_unknown_paper_id_fails(tmp_db):
    with pytest.raises(Exception):
        submit_metadata_and_boundaries.invoke({"paper_id": 99999, **_META})


def test_submit_metadata_question_only_paper(tmp_db, tmp_path):
    """Question-only papers: s_start/s_end may be omitted (stored NULL)."""
    q = tmp_path / "q.pdf"
    q.write_bytes(b"questions only")
    pid = database.register_paper(str(q))  # no solution PDF
    meta = {k: v for k, v in _META.items() if k not in ("s_start", "s_end")}
    assert submit_metadata_and_boundaries.invoke({"paper_id": pid, **meta}) is True
    row = database.get_paper(pid)
    assert (row["q_start"], row["q_end"]) == (1, 5)
    assert row["s_start"] is None and row["s_end"] is None


def test_submit_metadata_zero_means_no_solutions(tmp_db, tmp_path):
    """Prompt convention: agent passes 0 for solution bounds -> stored NULL."""
    pid = _paper_id(tmp_db, tmp_path)
    meta = {**_META, "s_start": 0, "s_end": 0}
    assert submit_metadata_and_boundaries.invoke({"paper_id": pid, **meta}) is True
    row = database.get_paper(pid)
    assert row["s_start"] is None and row["s_end"] is None


def test_submit_metadata_rejects_bad_boundaries(tmp_db, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    bad_cases = [
        {**_META, "q_start": 0},          # < 1
        {**_META, "q_start": 6, "q_end": 5},  # start > end
        {**_META, "s_start": 6, "s_end": None},  # s_end missing
        {**_META, "s_start": None, "s_end": 10},  # s_start missing
        {**_META, "s_start": -1, "s_end": 10},
    ]
    for bad in bad_cases:
        with pytest.raises(Exception):
            submit_metadata_and_boundaries.invoke({"paper_id": pid, **bad})


def test_submit_solution_without_question_fails(tmp_db, tmp_outputs, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    with pytest.raises(Exception):
        submit_solution.invoke({
            "paper_id": pid, "question_number": "1", "latex_content": "S",
        })


def test_questions_unique_per_paper(tmp_db, tmp_path):
    """DB-level UNIQUE(paper_id, question_number) backs the app upsert."""
    import sqlite3

    pid = _paper_id(tmp_db, tmp_path)
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO questions (paper_id, question_number) VALUES (?, 'dup')",
            (pid,),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO questions (paper_id, question_number) VALUES (?, 'dup')",
                (pid,),
            )
            conn.commit()
    finally:
        conn.close()


def test_submit_question_unknown_paper_id_fails(tmp_db, tmp_outputs):
    with pytest.raises(Exception):
        submit_question.invoke({
            "paper_id": 99999, "question_number": "1", "latex_content": "Q",
        })
    assert not (tmp_outputs / "99999").exists()  # no orphan dirs on bad id


def test_submit_solution_unknown_paper_id_fails(tmp_db, tmp_outputs):
    with pytest.raises(Exception):
        submit_solution.invoke({
            "paper_id": 99999, "question_number": "1", "latex_content": "S",
        })
    assert not (tmp_outputs / "99999").exists()


def test_verify_latex_valid():
    good = r"\begin{equation} F = ma \end{equation}"
    assert verify_latex_syntax.invoke({"latex_string": good}) == "Valid"


def test_verify_latex_mismatched_braces():
    bad = r"\textbf{unclosed"
    out = verify_latex_syntax.invoke({"latex_string": bad})
    assert out != "Valid" and "brace" in out.lower()


def test_verify_latex_mismatched_environment():
    bad = r"\begin{equation} x \end{align}"
    out = verify_latex_syntax.invoke({"latex_string": bad})
    assert out != "Valid"
    assert "mismatch" in out.lower() or "unclosed" in out.lower() or "end" in out.lower()


def test_verify_latex_stray_end():
    out = verify_latex_syntax.invoke({"latex_string": r"\end{equation}"})
    assert out != "Valid"


def test_submit_question_grouped_number(tmp_db, tmp_outputs, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    ok = submit_question.invoke({
        "paper_id": pid,
        "question_number": "15-17_paragraph",
        "latex_content": r"\begin{equation} F=ma \end{equation}",
    })
    assert ok == "saved"
    qdir = tmp_outputs / str(pid) / "15-17_paragraph"
    assert (qdir / "question.tex").is_file()
    assert (qdir / "figures").is_dir()
    conn = database.get_connection()
    try:
        row = conn.execute(
            "SELECT latex_folder, status FROM questions WHERE paper_id = ? AND question_number = ?",
            (pid, "15-17_paragraph"),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row["status"] == "draft"
    assert "15-17_paragraph" in row["latex_folder"]


def test_submit_question_upserts_on_recall(tmp_db, tmp_outputs, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    submit_question.invoke({"paper_id": pid, "question_number": "15a", "latex_content": "v1"})
    submit_question.invoke({"paper_id": pid, "question_number": "15a", "latex_content": "v2"})
    assert (tmp_outputs / str(pid) / "15a" / "question.tex").read_text() == "v2"
    conn = database.get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM questions WHERE paper_id = ? AND question_number = ?",
            (pid, "15a"),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert n == 1


@pytest.mark.parametrize("empty", ["", "   ", "no_solution_found"])
def test_submit_solution_graceful_placeholder(tmp_db, tmp_outputs, tmp_path, empty):
    pid = _paper_id(tmp_db, tmp_path)
    submit_question.invoke({"paper_id": pid, "question_number": "1", "latex_content": "Q"})
    assert submit_solution.invoke({
        "paper_id": pid, "question_number": "1", "latex_content": empty,
    }) == "saved"
    sol = (tmp_outputs / str(pid) / "1" / "solution.tex").read_text(encoding="utf-8")
    assert sol == dm.SOLUTION_PLACEHOLDER


def test_submit_solution_real_content_and_overwrite(tmp_db, tmp_outputs, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    submit_question.invoke({"paper_id": pid, "question_number": "2", "latex_content": "Q"})
    body = "Key: B\n" r"\begin{solution} $F=ma$ \end{solution}"
    assert verify_latex_syntax.invoke({"latex_string": body}) == "Valid"
    assert submit_solution.invoke({
        "paper_id": pid, "question_number": "2", "latex_content": body,
    }) == "saved"
    assert (tmp_outputs / str(pid) / "2" / "solution.tex").read_text() == body
    # Correction reuses the same question_number and overwrites.
    fixed = "Key: C\n" r"\begin{solution} $F=ma^2$ \end{solution}"
    assert submit_solution.invoke({
        "paper_id": pid, "question_number": "2", "latex_content": fixed,
    }) == "saved"
    assert (tmp_outputs / str(pid) / "2" / "solution.tex").read_text() == fixed


def test_submit_question_rejects_missing_figure(tmp_db, tmp_outputs, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    out = submit_question.invoke({
        "paper_id": pid,
        "question_number": "1",
        "latex_content": r"See \includegraphics{figures/ghost.png}",
    })
    assert out.startswith("NOT SAVED")
    assert "ghost.png" in out
    conn = database.get_connection()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM questions WHERE paper_id = ?", (pid,)
        ).fetchone()["c"]
    finally:
        conn.close()
    assert n == 0  # nothing saved on validation failure
    assert not (tmp_outputs / str(pid) / "1" / "question.tex").exists()


def test_submit_question_rejects_bad_latex(tmp_db, tmp_outputs, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    out = submit_question.invoke({
        "paper_id": pid, "question_number": "1", "latex_content": r"\textbf{unclosed",
    })
    assert out.startswith("NOT SAVED")


def test_submit_solution_requires_key_on_first_line(tmp_db, tmp_outputs, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    submit_question.invoke({"paper_id": pid, "question_number": "3", "latex_content": "Q"})
    out = submit_solution.invoke({
        "paper_id": pid, "question_number": "3",
        "latex_content": r"\begin{solution} $F=ma$ \end{solution}",
    })
    assert out.startswith("NOT SAVED")
    assert "first line" in out.lower()
    assert not (tmp_outputs / str(pid) / "3" / "solution.tex").exists()


def test_submit_solution_rejects_missing_figure(tmp_db, tmp_outputs, tmp_path):
    pid = _paper_id(tmp_db, tmp_path)
    submit_question.invoke({"paper_id": pid, "question_number": "4", "latex_content": "Q"})
    out = submit_solution.invoke({
        "paper_id": pid, "question_number": "4",
        "latex_content": "Key: A\n" r"See \includegraphics{figures/ghost.png}",
    })
    assert out.startswith("NOT SAVED")
    assert "ghost.png" in out


def test_end_to_end_preflight_to_submit(tmp_db, tmp_outputs, tmp_path):
    """Full corrected flow: pre-flight register -> UPDATE meta -> submit Q/S."""
    pid = _paper_id(tmp_db, tmp_path, tag="e2e")
    assert _submit_meta(pid) is True
    assert submit_question.invoke({
        "paper_id": pid, "question_number": "1", "latex_content": "Q1",
    }) == "saved"
    assert submit_solution.invoke({
        "paper_id": pid, "question_number": "1", "latex_content": "",
    }) == "saved"
    qdir = tmp_outputs / str(pid) / "1"
    assert (qdir / "question.tex").read_text() == "Q1"
    assert (qdir / "solution.tex").read_text() == dm.SOLUTION_PLACEHOLDER
