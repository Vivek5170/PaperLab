"""TeX-to-JSON segments shared by the papers and inbox routers.

Splitting reuses app/render.py:split_tex so the API and the Streamlit UI
render identically; this module only maps segments to download URLs.
"""
from __future__ import annotations

import urllib.parse
from pathlib import Path

import mistune

from app.render import _split_math, split_tex

# Same family as Streamlit's frontend (remark-gfm + remark-math):
# GFM tables, start-numbered ordered lists, strikethrough.
_MD = mistune.create_markdown(renderer="html", plugins=["table", "strikethrough"])


def figure_url(qdir: Path, paper_id: int, qn: str, abspath: str) -> str | None:
    try:
        rel = Path(abspath).resolve().relative_to(qdir.resolve())
    except (ValueError, OSError):
        return None
    if not (qdir / rel).is_file():
        return None
    return f"/api/papers/{paper_id}/questions/{qn}/figures/{rel.name}"


def rich_text(md_text: str) -> str:
    """Markdown -> HTML with math spans protected inline.

    Math pairing reuses render._split_math (the exact Streamlit rules).
    Math is replaced by an alphanumeric placeholder BEFORE the single
    Markdown pass, so formulas stay inside their paragraph exactly like
    Streamlit's one-shot render; the placeholders are swapped for KaTeX
    spans afterwards. Display-math `\\\\` doubling (meant for markdown-it
    halving) is halved back since Python-Markdown does not halve.
    """
    maths: list[tuple[str, bool]] = []
    protected: list[str] = []
    for part in _split_math(md_text):
        if part[0] == "math":
            _, inner, display = part
            if display:
                inner = inner.replace("\\\\", "\\")
            maths.append((inner, display))
            protected.append(f"PLMATH{len(maths) - 1}PL")
        else:
            protected.append(part[1])
    html = _MD("".join(protected))
    for i, (inner, display) in enumerate(maths):
        enc = urllib.parse.quote(inner, safe="")
        cls = "pl-math-block" if display else "pl-math"
        html = html.replace(
            f"PLMATH{i}PL",
            f'<span class="{cls}" data-tex="{enc}"'
            f' data-display="{1 if display else 0}"></span>',
        )
    return html


def _cell_to_json(items: list, qdir: Path, paper_id: int, qn: str) -> list:
    """One raw cell (list of (kind, value) items) -> JSON cell."""
    cell = []
    for ck, val in items:
        if ck == "fig":
            url = figure_url(qdir, paper_id, qn, val)
            cell.append({"kind": "fig", "url": url} if url
                        else {"kind": "text", "html": rich_text(str(val))})
        else:
            cell.append({"kind": "text", "html": rich_text(val)})
    return cell or [{"kind": "text", "html": ""}]


def tex_segments(tex: str, qdir: Path, paper_id: int, qn: str) -> list[dict]:
    out: list[dict] = []
    for kind, payload in split_tex(tex, qdir):
        if kind == "text":
            out.append({"kind": "text", "html": rich_text(payload)})
        elif kind == "fig":
            url = figure_url(qdir, paper_id, qn, payload) if payload else None
            if url:
                out.append({"kind": "fig", "url": url})
            else:
                out.append({"kind": "text",
                            "html": rich_text(f"(figure missing: {payload})")})
        else:  # table with inline figure cells
            out.append({
                "kind": "table",
                "header": [_cell_to_json(c, qdir, paper_id, qn)
                           for c in payload["header"]],
                "rows": [[_cell_to_json(c, qdir, paper_id, qn) for c in r]
                         for r in payload["rows"]],
            })
    return out
