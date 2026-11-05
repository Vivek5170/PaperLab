"""Tagging Inbox: questions with zero topic rows (admin)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

import database
import directory_manager
from backend.deps import require_admin

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
        try:
            qid = database.get_question_id(r["paper_id"], r["question_number"])
            links = []
            for code, _rank, src in database.get_question_links(qid):
                try:
                    path = database.topic_path(code)
                except ValueError:
                    path = code
                leaf = path.split("›")[-1].strip() or path
                links.append({"code": code, "path": path, "name": leaf,
                              "auto": src != "human"})
        except ValueError:
            links = []
        items.append({
            "paperId": r["paper_id"],
            "number": r["question_number"],
            "qtype": r["qtype"] or "unknown",
            "difficulty": r["difficulty"],
            "suggestion": r["topic_suggestion"],
            "topics": links,
        })
    return {"total": len(items), "items": items}
