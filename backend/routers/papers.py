"""Papers, questions, classification, registration.

Reads reuse database + directory_manager; TeX splitting reuses
app/render.py:split_tex so the API and Streamlit UI render identically.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import database
import directory_manager
from app.library import bucket_papers, filter_papers
from app.pairing import UPLOAD_DIR, delete_paper_everywhere, register_pair
from backend.deps import require_admin
from backend.segments import tex_segments

router = APIRouter()


def _paper_dict(row) -> dict:
    return {
        "id": row["id"],
        "title": row["paper_name"],
        "exam": row["exam_type"],
        "date": row["paper_date"],
        "institute": row["source_institute"],
        "status": row["status"] or "uploaded",
        "questionPdf": row["question_pdf_path"],
        "solutionPdf": row["solution_pdf_path"],
        "error": row["error"],
    }


def _require_paper(paper_id: int):
    row = database.get_paper(paper_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"paper {paper_id} not found")
    return row


def _qn_sort_key(qn: str):
    """Same ordering as the Streamlit reader (app/app.py:_qn_sort_key)."""
    m = re.match(r"^(?:([A-Za-z]+)-)?(\d+)(.*)$", qn or "")
    if not m:
        return (1, qn or "", 0, "")
    sec, num, rest = m.groups()
    return (0, sec or "", int(num), rest or "")


def _ordered_questions(paper_id: int):
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT question_number, qtype FROM questions WHERE paper_id = ?",
            (paper_id,),
        ).fetchall()
    finally:
        conn.close()
    return sorted(rows, key=lambda r: _qn_sort_key(r["question_number"]))


def _fig_url(qdir: Path, paper_id: int, qn: str, abspath: str) -> str | None:
    """Map a resolved figure path to its download URL (None when missing)."""
    from backend.segments import figure_url

    return figure_url(qdir, paper_id, qn, abspath)


def _tex_segments(tex: str, qdir: Path, paper_id: int, qn: str) -> list[dict]:
    return tex_segments(tex, qdir, paper_id, qn)


def _question_detail(paper_id: int, qn: str) -> dict:
    qdir = directory_manager.get_question_dir(paper_id, qn)
    try:
        qtex = (qdir / "question.tex").read_text(encoding="utf-8")
    except OSError:
        qtex = "*missing*"
    try:
        stex = (qdir / "solution.tex").read_text(encoding="utf-8")
    except OSError:
        stex = "*missing*"
    conn = database.get_connection()
    try:
        mrow = conn.execute(
            "SELECT id, qtype, difficulty, topic_suggestion FROM questions"
            " WHERE paper_id = ? AND question_number = ?",
            (paper_id, qn),
        ).fetchone()
    finally:
        conn.close()
    if mrow is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"question {qn} not found")
    links = []
    for code, _rank, src in database.get_question_links(mrow["id"]):
        try:
            path = database.topic_path(code)
        except ValueError:
            path = code
        links.append({"code": code, "path": path, "auto": src != "human"})
    return {
        "paperId": paper_id,
        "number": qn,
        "qtype": mrow["qtype"] or "unknown",
        "difficulty": mrow["difficulty"],
        "suggestion": mrow["topic_suggestion"],
        "topics": links,
        "question": _tex_segments(qtex, qdir, paper_id, qn),
        "solution": _tex_segments(stex, qdir, paper_id, qn),
    }


@router.get("")
def list_papers(query: str = "", exam: str = "All"):
    conn = database.get_connection()
    try:
        rows = conn.execute("SELECT * FROM papers ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    return [_paper_dict(r) for r in filter_papers(rows, query, exam)]


@router.get("/summary")
def library_summary():
    conn = database.get_connection()
    try:
        rows = conn.execute("SELECT * FROM papers").fetchall()
        counts = {
            pid: n
            for pid, n in conn.execute(
                "SELECT paper_id, COUNT(*) FROM questions GROUP BY paper_id"
            ).fetchall()
        }
        types: dict = {}
        for pid, qt, n in conn.execute(
            "SELECT paper_id, qtype, COUNT(*) FROM questions"
            " GROUP BY paper_id, qtype"
        ).fetchall():
            types.setdefault(pid, {})[qt or "unknown"] = n
    finally:
        conn.close()
    order = list(database.QTYPE_VALUES)
    summaries = {}
    for pid, t in types.items():
        parts = [f"{k} {t[k]}" for k in order if k in t]
        parts += [f"{k} {t[k]}" for k in t if k not in order]
        summaries[pid] = " - ".join(parts)
    return {"counts": counts, "types": summaries, "buckets": {
        k: len(v) for k, v in bucket_papers(rows).items()}}


@router.get("/meta")
def library_meta():
    return {
        "qtypes": list(database.QTYPE_VALUES),
        "difficulties": list(database.DIFFICULTY_VALUES),
    }


@router.get("/{paper_id}")
def get_paper(paper_id: int):
    return _paper_dict(_require_paper(paper_id))


@router.delete("/{paper_id}", dependencies=[Depends(require_admin)])
def delete_paper(paper_id: int):
    """Hard-delete: DB row, questions, token rows, Outputs, managed source PDFs."""
    _require_paper(paper_id)
    delete_paper_everywhere(paper_id)
    return {"paperId": paper_id, "deleted": True}


@router.get("/{paper_id}/questions")
def get_questions(paper_id: int):
    _require_paper(paper_id)
    return [_question_detail(paper_id, r["question_number"])
            for r in _ordered_questions(paper_id)]


@router.get("/{paper_id}/questions/{qn}/figures/{name}")
def get_figure(paper_id: int, qn: str, name: str):
    safe = Path(name).name

    safe = Path(name).name
    if safe != name or not safe:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad figure name")
    fig = directory_manager.get_question_dir(paper_id, qn) / "figures" / safe
    try:
        fig.resolve().relative_to(
            directory_manager.get_question_dir(paper_id, qn).resolve())
    except (ValueError, OSError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad figure name")
    if not fig.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "figure not found")
    return FileResponse(fig)


class ClassifyBody(BaseModel):
    qtype: str | None = None
    difficulty: str | None = Field(default=None)
    topicCodes: list[str] | None = None
    suggestion: str | None = None


@router.patch("/{paper_id}/questions/{qn}", dependencies=[Depends(require_admin)])
def classify_question(paper_id: int, qn: str, body: ClassifyBody):
    _require_paper(paper_id)
    try:
        qid = database.get_question_id(paper_id, qn)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    fields = body.model_fields_set
    try:
        if "qtype" in fields and body.qtype is not None:
            database.set_question_qtype(paper_id, qn, body.qtype)
        if "difficulty" in fields or "suggestion" in fields:
            # Present-with-null clears; absent leaves the stored value alone.
            conn = database.get_connection()
            try:
                row = conn.execute(
                    "SELECT difficulty, topic_suggestion FROM questions WHERE id = ?",
                    (qid,)).fetchone()
            finally:
                conn.close()
            database.set_question_difficulty(
                paper_id, qn,
                body.difficulty if "difficulty" in fields
                else (row["difficulty"] if row else None),
                topic_suggestion=(body.suggestion.strip()
                                   if "suggestion" in fields and body.suggestion is not None
                                   else (row["topic_suggestion"] or "" if row else "")),
            )
        if body.topicCodes is not None:
            database.set_question_topics(qid, body.topicCodes, src="human")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return _question_detail(paper_id, qn)


class PairItem(BaseModel):
    question: str
    solution: str | None = None


class RegisterBody(BaseModel):
    pairs: list[PairItem]


@router.post("/register", dependencies=[Depends(require_admin)])
def register_pairs(body: RegisterBody):
    out = []
    for p in body.pairs:
        q = (UPLOAD_DIR / Path(p.question).name)
        s = (UPLOAD_DIR / Path(p.solution).name) if p.solution else None
        pid, reused = register_pair(str(q), str(s) if s else None)
        out.append({"question": p.question, "paperId": pid, "reused": reused})
    return {"registered": out}
