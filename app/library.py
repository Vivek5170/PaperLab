"""Library/queue helpers: pure functions over paper rows (testable, UI-free)."""
from __future__ import annotations

import difflib
from pathlib import Path


def display_name(row) -> str:
    """Human-recognisable paper label: metadata title, else the PDF filename."""
    if row["paper_name"]:
        return row["paper_name"]
    qp = row["question_pdf_path"] if "question_pdf_path" in row.keys() else None
    if qp:
        return Path(qp).name
    return f"paper {row['id']}"


def filter_papers(rows: list, query: str = "", exam: str = "All") -> list:
    """Filter paper rows by exam and fuzzy name search (best matches first)."""
    out = [r for r in rows if exam == "All" or (r["exam_type"] or "") == exam]
    q = (query or "").strip().lower()
    if not q:
        return out
    scored = []
    for r in out:
        name = (r["paper_name"] or f"paper {r['id']}").lower()
        if q in name:
            scored.append((0.0, r))
            continue
        ratio = difflib.SequenceMatcher(None, q, name).ratio()
        if ratio > 0.3:
            scored.append((1.0 - ratio, r))
    return [r for _, r in sorted(scored, key=lambda t: t[0])]


def exam_options(rows: list) -> list[str]:
    """Sorted unique exam types present, for the filter dropdown."""
    return sorted({(r["exam_type"] or "Unknown") for r in rows})


def bucket_papers(rows: list) -> dict:
    """Split papers into workflow buckets for the Processing page."""
    buckets = {"queued": [], "running": [], "done": [], "failed": []}
    for r in rows:
        s = r["status"] or "uploaded"
        if s in ("uploaded",):
            buckets["queued"].append(r)
        elif s in ("indexing", "extracting"):
            buckets["running"].append(r)
        elif s == "done":
            buckets["done"].append(r)
        else:
            buckets["failed"].append(r)
    return buckets
