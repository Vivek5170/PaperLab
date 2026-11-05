"""Syllabus Map: topic tree CRUD (reads public, writes admin)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

import database
from backend.deps import require_admin
from backend.routers.search import bump_search_version

router = APIRouter()


def _topic_dict(row) -> dict:
    return {
        "code": row["code"],
        "parent": row["parent"],
        "level": row["level"],
        "name": row["name"],
        "descr": row["descr"],
        "rev": row["rev"],
    }


@router.get("/usage")
def topic_usage():
    """How many question tags point at each topic (delete guard signal)."""
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT topic_code, COUNT(*) FROM question_topics GROUP BY topic_code"
        ).fetchall()
    finally:
        conn.close()
    return {code: n for code, n in rows}


@router.get("")
def list_topics():
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT code, parent, level, name, descr, rev FROM topics "
            "ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()
    return [_topic_dict(r) for r in rows]


class CreateBody(BaseModel):
    parent: str | None = None
    level: str = "subtopic"
    name: str
    descr: str = ""


@router.post("", dependencies=[Depends(require_admin)])
def create_topic(body: CreateBody):
    try:
        if body.level == "module" or not body.parent:
            code = database.add_module(body.name)
        else:
            code = database.add_topic(body.parent, body.level, body.name, body.descr)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    bump_search_version()
    return {"code": code}


class UpdateBody(BaseModel):
    name: str
    descr: str = ""
    rev: int


@router.patch("/{code}", dependencies=[Depends(require_admin)])
def update_topic(code: str, body: UpdateBody):
    try:
        new_rev = database.update_topic(code, body.name, body.descr, int(body.rev))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    bump_search_version()
    return {"code": code, "rev": new_rev}


class MoveBody(BaseModel):
    newParent: str


@router.post("/{code}/move", dependencies=[Depends(require_admin)])
def move_topic(code: str, body: MoveBody):
    try:
        database.move_topic(code, body.newParent)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    bump_search_version()
    return {"code": code, "parent": body.newParent}


@router.delete("/{code}", dependencies=[Depends(require_admin)])
def delete_topic(code: str):
    try:
        database.delete_topic(code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    bump_search_version()
    return {"code": code, "deleted": True}
