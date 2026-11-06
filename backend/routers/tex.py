"""Raw TeX endpoints for the experimental editor workspace (/lab/edit/...).

Read-only preview reuses backend.segments.tex_segments (the exact reader
pipeline) with the real question dir, so figure references resolve to the
same URLs. Saves are archivist-only, LaTeX-validated BEFORE writing, and
keep a timestamped .bak backup next to the file (never inside figures/,
never matching render-cache names).
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

import database
import directory_manager
from backend.deps import require_admin
from backend.segments import tex_segments

router = APIRouter()

PARTS = ("question", "solution")
MAX_TEX_BYTES = 500_000


def _qdir(paper_id: int, qn: str) -> Path:
    try:
        return directory_manager.get_question_dir(paper_id, qn)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad paper or question")


def _require_tex(paper_id: int, qn: str, part: str) -> Path:
    if part not in PARTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "part must be question|solution")
    if database.get_paper(paper_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"paper {paper_id} not found")
    texp = _qdir(paper_id, qn) / f"{part}.tex"
    if not texp.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tex not found")
    return texp


def _verify_or_raise(tex: str) -> None:
    from tools_extractor import verify_latex_syntax

    try:
        v = verify_latex_syntax.invoke({"latex_string": tex})
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"tex validation failed: {exc}")
    if v != "Valid":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid LaTeX: {v}")


class PreviewBody(BaseModel):
    tex: str = Field(min_length=0, max_length=MAX_TEX_BYTES)
    part: str = "question"


class SaveBody(BaseModel):
    part: str
    tex: str = Field(min_length=1, max_length=MAX_TEX_BYTES)
    expectedSha: str | None = None


@router.get("/{paper_id}/questions/{qn}/tex", dependencies=[Depends(require_admin)])
def get_tex(paper_id: int, qn: str, part: str = Query(default="question")):
    """Raw .tex text for the editor. Archivist-only (unlike the reader)."""
    texp = _require_tex(paper_id, qn, part)
    data = texp.read_bytes()
    return {
        "paperId": paper_id,
        "number": qn,
        "part": part,
        "fileName": f"{part}.tex",
        "tex": data.decode("utf-8"),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


@router.post("/{paper_id}/questions/{qn}/tex/preview", dependencies=[Depends(require_admin)])
def preview_tex(paper_id: int, qn: str, body: PreviewBody):
    """Render draft tex to reader segments WITHOUT writing anything."""
    if body.part not in PARTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "part must be question|solution")
    if database.get_paper(paper_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"paper {paper_id} not found")
    qdir = _qdir(paper_id, qn)
    return {"segments": tex_segments(body.tex, qdir, paper_id, qn)}


@router.patch("/{paper_id}/questions/{qn}/tex", dependencies=[Depends(require_admin)])
def save_tex(paper_id: int, qn: str, body: SaveBody):
    """Validate then save raw .tex; keeps a timestamped .bak backup."""
    texp = _require_tex(paper_id, qn, body.part)
    current = texp.read_bytes()
    if body.expectedSha and hashlib.sha256(current).hexdigest() != body.expectedSha:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "tex changed since you loaded it; reload and reapply your edits")
    _verify_or_raise(body.tex)
    backup = texp.with_name(f"{texp.name}.bak-{int(time.time())}")
    backup.write_bytes(current)
    data = body.tex.encode("utf-8")
    texp.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    qdir = texp.parent
    return {
        "paperId": paper_id,
        "number": qn,
        "part": body.part,
        "saved": True,
        "sha256": sha,
        "backup": backup.name,
        "segments": tex_segments(body.tex, qdir, paper_id, qn),
    }
