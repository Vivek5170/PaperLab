"""Tagging Inbox: questions with zero topic rows (admin)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

import database
import directory_manager
from backend.deps import require_admin
from backend.segments import tex_segments

router = APIRouter()


@router.get("", dependencies=[Depends(require_admin)])
def get_inbox():
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT q.paper_id, q.question_number, q.qtype, q.difficulty,"
            " q.topic_suggestion FROM questions q"
            " LEFT JOIN question_topics t ON t.question_id = q.id"
            " WHERE t.question_id IS NULL"
            " ORDER BY q.paper_id, q.id"
        ).fetchall()
    finally:
        conn.close()
    items = []
    for r in rows:
        qdir = directory_manager.get_question_dir(r["paper_id"], r["question_number"])
        try:
            qtex = (qdir / "question.tex").read_text(encoding="utf-8")
        except OSError:
            qtex = "*missing*"
        try:
            qid = database.get_question_id(r["paper_id"], r["question_number"])
            links = []
            for code, _rank, src in database.get_question_links(qid):
                try:
                    path = database.topic_path(code)
                except ValueError:
                    path = code
                links.append({"code": code, "path": path, "auto": src != "human"})
        except ValueError:
            links = []
        items.append({
            "paperId": r["paper_id"],
            "number": r["question_number"],
            "qtype": r["qtype"] or "unknown",
            "difficulty": r["difficulty"],
            "suggestion": r["topic_suggestion"],
            "topics": links,
            "question": tex_segments(qtex, qdir, r["paper_id"], r["question_number"]),
        })
    return items
