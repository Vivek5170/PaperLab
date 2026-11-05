"""Staging area + pair suggestion (admin).

Upload bytes are written straight into directory_manager.UPLOADS_DIR;
pairing and registration reuse app/pairing.py.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel

import directory_manager
from app.pairing import UPLOAD_DIR, auto_pair, split_candidates
from backend.deps import require_admin

router = APIRouter()


def _staged() -> list[str]:
    if not UPLOAD_DIR.is_dir():
        return []
    return sorted(p.name for p in UPLOAD_DIR.glob("*.pdf"))


@router.get("", dependencies=[Depends(require_admin)])
def list_uploads():
    return {"staged": _staged()}


@router.post("", dependencies=[Depends(require_admin)])
async def upload_files(files: list[UploadFile]):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        name = Path(f.filename or "").name
        if not name.lower().endswith(".pdf"):
            continue
        target = UPLOAD_DIR / name
        if target.resolve().parent != UPLOAD_DIR.resolve():
            continue
        target.write_bytes(await f.read())
        saved.append(name)
    return {"saved": saved}


class DeleteBody(BaseModel):
    names: list[str]


@router.delete("", dependencies=[Depends(require_admin)])
def delete_uploads(body: DeleteBody):
    deleted = []
    for name in body.names:
        target = UPLOAD_DIR / Path(name).name
        try:
            if target.resolve().parent != UPLOAD_DIR.resolve():
                continue
        except OSError:
            continue
        try:
            if target.is_file():
                target.unlink()
                deleted.append(target.name)
        except OSError:
            continue
    return {"deleted": deleted}


@router.get("/pairs/suggest", dependencies=[Depends(require_admin)])
def suggest_pairs():
    staged = _staged()
    q_names, s_names = split_candidates(staged)
    pairs = auto_pair(q_names, s_names)
    return {
        "pairs": [{"question": q, "solution": s} for q, s in pairs],
        "solutions": s_names,
    }


@router.delete("/clear", dependencies=[Depends(require_admin)])
def clear_uploads():
    names = _staged()
    for n in names:
        try:
            (UPLOAD_DIR / n).unlink()
        except OSError:
            pass
    return {"deleted": names}
