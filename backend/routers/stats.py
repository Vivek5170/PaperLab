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
    return {
        "renderCache": {"bytes": _size(render), "files": len(render)},
        "cleanedPdfs": {"bytes": _size(deletable), "files": len(deletable),
                        "protected": len(protected)},
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
