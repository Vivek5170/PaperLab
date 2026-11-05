"""Usage Ledger: token accounting (admin). Same math as the Streamlit view."""
from __future__ import annotations

from fastapi import APIRouter, Depends

import config
import database
from backend.deps import require_admin
from run_pipeline import summarize_tokens

router = APIRouter()


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
