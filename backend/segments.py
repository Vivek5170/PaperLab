"""TeX-to-JSON segments shared by the papers and inbox routers.

Splitting reuses app/render.py:split_tex so the API and the Streamlit UI
render identically; this module only maps segments to download URLs.
"""
from __future__ import annotations

from pathlib import Path

from app.render import split_tex


def figure_url(qdir: Path, paper_id: int, qn: str, abspath: str) -> str | None:
    try:
        rel = Path(abspath).resolve().relative_to(qdir.resolve())
    except (ValueError, OSError):
        return None
    if not (qdir / rel).is_file():
        return None
    return f"/api/papers/{paper_id}/questions/{qn}/figures/{rel.name}"


def _cell_to_json(items: list, qdir: Path, paper_id: int, qn: str) -> list:
    """One raw cell (list of (kind, value) items) -> JSON cell."""
    cell = []
    for ck, val in items:
        if ck == "fig":
            url = figure_url(qdir, paper_id, qn, val)
            cell.append({"kind": "fig", "url": url} if url
                        else {"kind": "text", "markdown": str(val)})
        else:
            cell.append({"kind": "text", "markdown": val})
    return cell or [{"kind": "text", "markdown": ""}]


def tex_segments(tex: str, qdir: Path, paper_id: int, qn: str) -> list[dict]:
    out: list[dict] = []
    for kind, payload in split_tex(tex, qdir):
        if kind == "text":
            out.append({"kind": "text", "markdown": payload})
        elif kind == "fig":
            url = figure_url(qdir, paper_id, qn, payload) if payload else None
            if url:
                out.append({"kind": "fig", "url": url})
            else:
                out.append({"kind": "text", "markdown": f"(figure missing: {payload})"})
        else:  # table with inline figure cells
            out.append({
                "kind": "table",
                "header": [_cell_to_json(c, qdir, paper_id, qn)
                           for c in payload["header"]],
                "rows": [[_cell_to_json(c, qdir, paper_id, qn) for c in r]
                         for r in payload["rows"]],
            })
    return out
