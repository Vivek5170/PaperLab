"""Figure ops for one question: list / add / re-crop / replace / delete.

Mirrors app/app.py:_figure_manager exactly (same helpers, same LaTeX
validation, same provenance stamping) with two additions the Streamlit UI
lacks: replace-in-place and a trash can, so nothing is ever truly lost
until the user empties it. Trash files live inside figures/ with a `_`
prefix, which app/figures.list_figures already ignores.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from PIL import Image
from pydantic import BaseModel

import directory_manager
from app.figures import (
    FIGURE_EXTS,
    _record_mode,
    crop_image_file,
    figure_side,
    insert_figure_ref,
    list_figures,
    next_figure_name,
    referencing_tex,
    remove_figure_refs,
    save_uploaded_figure,
)
from backend.deps import require_admin

router = APIRouter()


def _figures_dir(paper_id: int, qn: str) -> Path:
    return directory_manager.get_question_dir(paper_id, qn) / "figures"


def _resolve(figures: Path, name: str, allow_trash: bool = False) -> Path:
    safe = Path(name).name
    if not safe or safe != name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad filename")
    if allow_trash:
        if not safe.startswith("_trash_"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "not a trashed file")
    else:
        if safe.startswith("_") or Path(safe).suffix.lower() not in FIGURE_EXTS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad filename")
    target = figures / safe
    try:
        if target.resolve().parent != figures.resolve():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad filename")
    except OSError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad filename")
    return target


def _mode_of(figures: Path, name: str) -> str | None:
    try:
        sidecar = figures / "_modes.json"
        if sidecar.is_file():
            return json.loads(sidecar.read_text(encoding="utf-8")).get(name)
    except Exception:
        pass
    return None


def _dims(path: Path) -> tuple[int | None, int | None]:
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None, None


def figure_dict(figures: Path, paper_id: int, qn: str, name: str) -> dict:
    qdir = figures.parent
    w, h = _dims(figures / name)
    return {
        "name": name,
        "side": figure_side(name),
        "usedIn": referencing_tex(qdir, name),
        "mode": _mode_of(figures, name),
        "url": f"/api/papers/{paper_id}/questions/{qn}/figures/{name}",
        "width": w,
        "height": h,
    }


def _trash(figures: Path, name: str) -> str:
    """Move a figure file into the trash; returns the trash filename."""
    trash_name = f"_trash_{int(time.time())}_{name}"
    (figures / name).rename(figures / trash_name)
    return trash_name


def _verify_or_raise(tex: str) -> None:
    from tools_extractor import verify_latex_syntax

    v = verify_latex_syntax.invoke({"latex_string": tex})
    if v != "Valid":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid LaTeX: {v}")


@router.get("", dependencies=[Depends(require_admin)])
def list_question_figures(paper_id: int, qn: str):
    figures = _figures_dir(paper_id, qn)
    return [figure_dict(figures, paper_id, qn, p.name) for p in list_figures(figures.parent)]


@router.get("/trash", dependencies=[Depends(require_admin)])
def list_trash(paper_id: int, qn: str):
    figures = _figures_dir(paper_id, qn)
    out = []
    if figures.is_dir():
        for p in sorted(figures.iterdir()):
            if p.is_file() and p.name.startswith("_trash_"):
                rest = p.name[len("_trash_"):]
                _ts, _, original = rest.partition("_")
                out.append({"name": p.name, "original": original or p.name,
                            "keptAt": _ts})
    return out


class CropBody(BaseModel):
    left: float
    top: float
    right: float
    bottom: float


@router.patch("/{name}", dependencies=[Depends(require_admin)])
def crop_figure(paper_id: int, qn: str, name: str, body: CropBody):
    figures = _figures_dir(paper_id, qn)
    target = _resolve(figures, name)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "figure not found")
    _trash_name = _trash(figures, name)
    trashed = figures / _trash_name
    data = trashed.read_bytes()
    target.write_bytes(data)
    try:
        crop_image_file(target, (body.left, body.top, body.right, body.bottom))
    except ValueError as exc:
        # Roll back: restore the exact pre-crop bytes, drop the trash copy.
        target.write_bytes(data)
        trashed.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return figure_dict(figures, paper_id, qn, name)


@router.put("/{name}", dependencies=[Depends(require_admin)])
async def replace_figure(paper_id: int, qn: str, name: str, file: UploadFile = File(...)):
    figures = _figures_dir(paper_id, qn)
    target = _resolve(figures, name)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "figure not found")
    data = await file.read()
    try:
        Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "upload is not a readable image")
    _trash(figures, name)
    target.write_bytes(data)
    _record_mode(figures, name, "manual")
    return figure_dict(figures, paper_id, qn, name)


@router.delete("/{name}", dependencies=[Depends(require_admin)])
def delete_figure(paper_id: int, qn: str, name: str):
    figures = _figures_dir(paper_id, qn)
    target = _resolve(figures, name)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "figure not found")
    qdir = figures.parent
    refs_before = referencing_tex(qdir, name)
    for which in refs_before:
        p = qdir / ("question.tex" if which == "question" else "solution.tex")
        new, removed = remove_figure_refs(p.read_text(encoding="utf-8"), name)
        if removed:
            _verify_or_raise(new)
            p.write_text(new, encoding="utf-8")
    trash_name = _trash(figures, name)
    return {"deleted": name, "trash": trash_name, "wasUsedIn": refs_before}


@router.post("/{name}/restore", dependencies=[Depends(require_admin)])
def restore_figure(paper_id: int, qn: str, name: str):
    figures = _figures_dir(paper_id, qn)
    trashed = _resolve(figures, name, allow_trash=True)
    if not trashed.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "trashed file not found")
    rest = name[len("_trash_"):]
    _ts, _, original = rest.partition("_")
    dest = figures / original
    if dest.exists():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"{original} exists - delete or rename it first")
    trashed.rename(dest)
    return figure_dict(figures, paper_id, qn, original)


@router.delete("/trash/{name}", dependencies=[Depends(require_admin)])
def empty_trash_item(paper_id: int, qn: str, name: str):
    figures = _figures_dir(paper_id, qn)
    trashed = _resolve(figures, name, allow_trash=True)
    if not trashed.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "trashed file not found")
    trashed.unlink()
    return {"deleted": name}


@router.post("", dependencies=[Depends(require_admin)])
async def add_figure(
    paper_id: int,
    qn: str,
    target: str = Form(...),
    filename: str = Form(""),
    file: UploadFile = File(...),
):
    if target not in ("question", "solution"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "target must be question|solution")
    qdir = directory_manager.get_question_dir(paper_id, qn)
    figures = qdir / "figures"
    data = await file.read()
    side = target
    name = filename.strip() or next_figure_name(qdir, side)
    try:
        dest = save_uploaded_figure(qdir, name, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    texp = qdir / ("question.tex" if target == "question" else "solution.tex")
    try:
        original = texp.read_text(encoding="utf-8") if texp.is_file() else ""
        new = insert_figure_ref(original, dest.name)
        _verify_or_raise(new)
    except HTTPException:
        dest.unlink()  # roll back: don't strand the file
        raise
    texp.write_text(new, encoding="utf-8")
    return figure_dict(figures, paper_id, qn, dest.name)
