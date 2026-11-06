"""Usage Ledger: token accounting (admin). Same math as the Streamlit view."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends

import config
import database
import directory_manager
from backend.deps import require_admin
from run_pipeline import summarize_tokens

router = APIRouter()

# Render-cache PNGs written by render_tex_to_png: Streamlit's _<label>.png
# plus the web endpoint's web_<part>.png. Content-hash guarded (.src_hash),
# so any deleted file recompiles on next Render click. Never match figure
# files (qfig*/sfig*/fig*).
RENDER_CACHE_NAMES = ("_question.png", "_solution.png")


def _render_cache_files(outputs: Path) -> list[Path]:
    out = []
    if outputs.is_dir():
        for p in outputs.rglob("*.png"):
            if p.name in RENDER_CACHE_NAMES or p.name.startswith("web_"):
                out.append(p)
    return out


def _protected_cleaned() -> set[str]:
    """Absolute cleaned-dir paths referenced by papers (never purge these)."""
    conn = database.get_connection()
    try:
        refs = {r[0] for r in conn.execute(
            "SELECT question_pdf_path FROM papers").fetchall()}
        refs |= {r[0] for r in conn.execute(
            "SELECT solution_pdf_path FROM papers").fetchall()}
    finally:
        conn.close()
    cleaned = str(directory_manager.CLEANED_DIR.resolve())
    keep = set()
    for r in refs:
        if not r:
            continue
        try:
            rp = str(Path(r).resolve())
        except OSError:
            continue
        if rp == cleaned or rp.startswith(cleaned + os.sep):
            keep.add(rp)
    return keep


def _purgeable_cleaned() -> tuple[list[Path], list[Path]]:
    """(deletable, protected) cleaned-dir files."""
    keep = _protected_cleaned()
    cdir = directory_manager.CLEANED_DIR
    deletable, protected = [], []
    if cdir.is_dir():
        for p in sorted(cdir.iterdir()):
            if not p.is_file() or p.is_symlink():
                continue
            try:
                rp = str(p.resolve())
            except OSError:
                continue
            (protected if rp in keep else deletable).append(p)
    return deletable, protected


def _is_crop_pdf(p: Path) -> bool:
    return p.suffix.lower() == ".pdf" and p.stem.endswith("_crop")


def _crop_files() -> list[Path]:
    """Crop canvases living next to managed sources in data/archive/."""
    adir = directory_manager.ARCHIVE_DIR
    out = []
    if adir.is_dir():
        for p in sorted(adir.iterdir()):
            if p.is_file() and not p.is_symlink() and _is_crop_pdf(p):
                out.append(p)
    return out


def _protected_crop() -> set[str]:
    """Absolute crop paths referenced by papers (never purge these)."""
    conn = database.get_connection()
    try:
        refs = {r[0] for r in conn.execute(
            "SELECT question_pdf_path FROM papers").fetchall()}
        refs |= {r[0] for r in conn.execute(
            "SELECT solution_pdf_path FROM papers").fetchall()}
    finally:
        conn.close()
    keep = set()
    for r in refs:
        if not r or not str(r).endswith(".pdf"):
            continue
        try:
            rp = str(Path(r).resolve())
        except OSError:
            continue
        if Path(rp).stem.endswith("_crop"):
            keep.add(rp)
    return keep


def _purgeable_crop() -> tuple[list[Path], list[Path]]:
    """(deletable, protected) crop canvases."""
    keep = _protected_crop()
    deletable, protected = [], []
    for p in _crop_files():
        try:
            rp = str(p.resolve())
        except OSError:
            continue
        (protected if rp in keep else deletable).append(p)
    return deletable, protected


def _paper_dict(row) -> dict:
    return {
        "id": row["id"],
        "title": row["paper_name"],
        "exam": row["exam_type"],
        "date": row["paper_date"],
        "status": row["status"] or "uploaded",
        "error": row["error"],
        "elapsedSec": row["elapsed_sec"],
    }


@router.get("", dependencies=[Depends(require_admin)])
def get_stats():
    pricing = config.PRICING
    conn = database.get_connection()
    try:
        papers = [_paper_dict(r) for r in conn.execute(
            "SELECT * FROM papers ORDER BY id DESC").fetchall()]
    finally:
        conn.close()

    def _phase_cost(ph: dict) -> float:
        return (
            (ph.get("input", 0) - ph.get("cache_read", 0)) / 1e6
            * pricing["input_per_mtok"]
            + ph.get("cache_read", 0) / 1e6 * pricing["cache_read_per_mtok"]
            + ph.get("output", 0) / 1e6 * pricing["output_per_mtok"]
        )

    rows, phases = [], {}
    totals = {"turns": 0, "cost": 0.0, "tagging": 0.0}
    for p in papers:
        s = summarize_tokens(p["id"])
        t = s["total"]
        if not t["turns"]:
            continue
        tagging = _phase_cost(s["per_phase"].get("topics", {}))
        totals["turns"] += t["turns"]
        totals["cost"] += s["cost_usd"]
        totals["tagging"] += tagging
        rows.append({
            "paper": f"#{p['id']} {(p['title'] or '')[:40]}",
            "status": p["status"],
            "turns": t["turns"],
            "input": t["input"],
            "cached": t["cache_read"],
            "output": t["output"],
            "reasoning": t["reasoning"],
            "wall": f"{p['elapsedSec']:.0f}s" if p["elapsedSec"] else "-",
            "extraction": round(s["cost_usd"] - tagging, 4),
            "tagging": round(tagging, 4),
            "total": round(s["cost_usd"], 4),
        })
        for ph, pv in s["per_phase"].items():
            slot = phases.setdefault(
                ph, {"phase": ph, "turns": 0, "fresh": 0, "cached": 0,
                     "output": 0, "cost": 0.0})
            slot["turns"] += pv["turns"]
            slot["fresh"] += pv["input"] - pv["cache_read"]
            slot["cached"] += pv["cache_read"]
            slot["output"] += pv["output"]
            slot["cost"] = round(slot["cost"] + _phase_cost(pv), 4)
    return {
        "totalCost": round(totals["cost"], 2),
        "extraction": round(totals["cost"] - totals["tagging"], 2),
        "tagging": round(totals["tagging"], 2),
        "turns": totals["turns"],
        "currencyDefault": config.CURRENCY_DEFAULT,
        "usdToInr": config.USD_TO_INR,
        "pricing": pricing,
        "rows": rows,
        "phases": sorted(phases.values(), key=lambda r: r["phase"]),
        "errors": [{"paper": p["id"], "error": p["error"]}
                   for p in papers if p["error"]],
    }


def _size(files: list[Path]) -> int:
    total = 0
    for p in files:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


@router.get("/disk", dependencies=[Depends(require_admin)])
def disk_usage():
    """Reclaimable disk: render-cache PNGs + unreferenced cleaned PDFs.

    Render cache recompiles on demand; cleaned intermediates rebuild from
    the question PDF on the next run. DB-referenced files are counted as
    protected, never purgeable.
    """
    render = _render_cache_files(directory_manager.OUTPUT_BASE)
    deletable, protected = _purgeable_cleaned()
    crop_del, crop_keep = _purgeable_crop()
    return {
        "renderCache": {"bytes": _size(render), "files": len(render)},
        "cleanedPdfs": {"bytes": _size(deletable), "files": len(deletable),
                        "protected": len(protected)},
        "cropPdfs": {"bytes": _size(crop_del), "files": len(crop_del),
                     "protected": len(crop_keep)},
    }


@router.delete("/disk/render", dependencies=[Depends(require_admin)])
def purge_render_cache():
    files = _render_cache_files(directory_manager.OUTPUT_BASE)
    freed, gone = 0, 0
    for p in files:
        try:
            freed += p.stat().st_size
            p.unlink()
            gone += 1
        except OSError:
            continue
    return {"deleted": gone, "bytes": freed}


@router.delete("/disk/cleaned", dependencies=[Depends(require_admin)])
def purge_cleaned_pdfs():
    deletable, _ = _purgeable_cleaned()
    freed, gone = 0, 0
    for p in deletable:
        try:
            freed += p.stat().st_size
            p.unlink()
            gone += 1
        except OSError:
            continue
    return {"deleted": gone, "bytes": freed}


@router.delete("/disk/intermediates", dependencies=[Depends(require_admin)])
def purge_intermediates():
    """One-shot purge of both regenerable states: crop canvases in
    data/archive plus unreferenced cleaned PDFs. DB-referenced files are
    kept. Crop canvases rebuild from cleaned PDFs; cleaned PDFs rebuild
    from the question PDF on the next run."""
    freed, gone, n_clean, n_crop = 0, 0, 0, 0
    for p in _purgeable_cleaned()[0]:
        try:
            freed += p.stat().st_size
            p.unlink()
            gone += 1
            n_clean += 1
        except OSError:
            continue
    for p in _purgeable_crop()[0]:
        try:
            freed += p.stat().st_size
            p.unlink()
            gone += 1
            n_crop += 1
        except OSError:
            continue
    return {"deleted": gone, "bytes": freed, "cleaned": n_clean, "crop": n_crop}


def _resolve_managed(stored: str | None) -> Path | None:
    """Resolve a DB-stored PDF path to an existing absolute file.

    Stored values may be absolute or bare filenames (older rows); try the
    value as-is, then data/archive/, then data/cleaned/. Returns None when
    nothing exists on disk.
    """
    if not stored:
        return None
    cands = [Path(stored)]
    base = Path(stored).name
    cands.append(directory_manager.ARCHIVE_DIR / base)
    cands.append(directory_manager.CLEANED_DIR / base)
    for c in cands:
        try:
            if c.is_file() and not c.is_symlink():
                return c.resolve()
        except OSError:
            continue
    return None


def _all_db_pdf_refs() -> set[str]:
    """Every question/solution PDF string stored by papers (raw + resolved)."""
    conn = database.get_connection()
    try:
        rows = conn.execute(
            "SELECT question_pdf_path, solution_pdf_path FROM papers").fetchall()
    finally:
        conn.close()
    out = set()
    for q, s in rows:
        for v in (q, s):
            if not v:
                continue
            out.add(str(v))
            try:
                out.add(str(Path(v).resolve()))
            except OSError:
                pass
    return out


def _paper_pdf_entries() -> tuple[list[dict], list[dict]]:
    """(per-paper files, unlinked files) for the selective PDF deleter.

    Per-paper entries mirror the DB references (deleting one also clears
    the reference so nothing dangles). Unlinked entries are archive/cleaned
    PDFs no paper points at (crop canvases excluded — they belong to the
    intermediates purge).
    """
    conn = database.get_connection()
    try:
        papers = conn.execute(
            "SELECT id, paper_name, question_pdf_path, solution_pdf_path"
            " FROM papers ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    refs = _all_db_pdf_refs()
    per_paper = []
    for pid, name, qpath, spath in papers:
        # Group by resolved file: a combined "QP, Key & Solutions" PDF
        # referenced by both columns is ONE row, not two selections.
        groups: dict[str, dict] = {}
        for field, kind, stored in (
                ("question_pdf_path", "question", qpath),
                ("solution_pdf_path", "solution", spath)):
            if not stored:
                continue
            rp = _resolve_managed(stored)
            key = str(rp) if rp is not None else f"stored:{stored}"
            slot = groups.setdefault(key, {"rp": rp, "items": []})
            slot["items"].append((field, kind, str(stored)))
        files = []
        for key, slot in groups.items():
            rp = slot["rp"]
            items = slot["items"]
            kinds = sorted({k for _, k, _ in items})
            try:
                size = rp.stat().st_size if rp else 0
            except OSError:
                size = 0
            first_stored = items[0][2]
            files.append({
                "kind": "both" if len(kinds) > 1 else kinds[0],
                "field": items[0][0],
                "fields": [f for f, _, _ in items],
                "name": Path(first_stored).name,
                "stored": first_stored,
                "storedAll": [s for _, _, s in items],
                "exists": rp is not None,
                "bytes": size,
            })
        per_paper.append({"id": pid, "name": name, "files": files})
    seen = set()

    def _collect(root: Path, location: str, skip_crop: bool):
        if not root.is_dir():
            return
        for p in sorted(root.iterdir()):
            if not p.is_file() or p.is_symlink():
                continue
            if p.suffix.lower() != ".pdf":
                continue
            if skip_crop and _is_crop_pdf(p):
                continue
            try:
                rp = str(p.resolve())
            except OSError:
                continue
            if rp in refs or str(p) in refs:
                continue
            key = (location, p.name)
            if key in seen:
                continue
            seen.add(key)
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            unlinked.append({"name": p.name, "location": location, "bytes": size})

    unlinked: list[dict] = []
    _collect(directory_manager.ARCHIVE_DIR, "archive", skip_crop=True)
    _collect(directory_manager.CLEANED_DIR, "cleaned", skip_crop=False)
    return per_paper, unlinked


@router.get("/pdfs", dependencies=[Depends(require_admin)])
def paper_pdfs():
    """Selectable QP / solution PDFs per paper plus unlinked PDFs."""
    per_paper, unlinked = _paper_pdf_entries()
    return {"papers": per_paper, "unlinked": unlinked}


@router.delete("/pdfs", dependencies=[Depends(require_admin)])
def delete_paper_pdfs(body: dict):
    """Delete selected PDFs; DB references to deleted files are cleared.

    Body: {"paths": [stored DB strings], "unlinked": [{location, name}]}.
    Only files inside the data tree are ever touched; anything outside is
    reported, never deleted. Returns counts plus cleared references.
    """
    data_roots = set()
    for _root in (directory_manager.ARCHIVE_DIR, directory_manager.CLEANED_DIR,
                  directory_manager.DATA_ROOT):
        try:
            data_roots.add(_root.resolve())
        except OSError:
            continue
    deleted, freed, cleared, missing, refused = 0, 0, [], [], []
    targets: list[tuple[str | None, Path | None]] = []
    for stored in body.get("paths") or []:
        targets.append((str(stored), _resolve_managed(stored)))
    for item in body.get("unlinked") or []:
        loc = (item or {}).get("location")
        name = (item or {}).get("name")
        root = {"archive": directory_manager.ARCHIVE_DIR,
                "cleaned": directory_manager.CLEANED_DIR}.get(loc)
        rp = None
        if root is not None and name and Path(name).name == name:
            cand = root / name
            try:
                if cand.is_file() and not cand.is_symlink():
                    rp = cand.resolve()
            except OSError:
                rp = None
        targets.append((None, rp))

    conn = database.get_connection()
    try:
        # Group by resolved file so one file sent twice (e.g. QP + solution
        # sharing a combined PDF) is unlinked once; references still clear.
        by_file: dict[str, dict] = {}
        for stored, rp in targets:
            if rp is None:
                missing.append(stored or "(unknown file)")
                continue
            inside = False
            for _base in data_roots:
                try:
                    if rp.is_relative_to(_base):
                        inside = True
                        break
                except (OSError, ValueError):
                    continue
            if not inside:
                refused.append(stored or str(rp))
                continue
            slot = by_file.setdefault(str(rp), {"rp": rp, "stored": []})
            if stored and stored not in slot["stored"]:
                slot["stored"].append(stored)
        for _key, slot in by_file.items():
            rp = slot["rp"]
            try:
                freed += rp.stat().st_size
                rp.unlink()
            except OSError:
                missing.extend(slot["stored"] or [str(rp)])
                continue
            deleted += 1
            for stored in slot["stored"]:
                for field in ("question_pdf_path", "solution_pdf_path"):
                    cur = conn.execute(
                        f"SELECT id FROM papers WHERE {field} = ?",
                        (stored,)).fetchall()
                    if cur:
                        conn.execute(
                            f"UPDATE papers SET {field} = NULL WHERE {field} = ?",
                            (stored,))
                        for (pid,) in cur:
                            cleared.append({"paperId": pid, "field": field})
        conn.commit()
    finally:
        conn.close()
    return {"deleted": deleted, "bytes": freed, "cleared": cleared,
            "missing": missing, "refused": refused}
