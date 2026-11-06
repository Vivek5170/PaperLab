"""File-level figure ops for the Library reader (no Streamlit calls).

All operations work on image FILES only: re-cropping shrinks the existing
raster (it cannot grow beyond it -- re-crop from the PDF via the agent for
that), uploads attach an already-cropped image, delete removes the file
plus its tex references. Headless-testable.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image

FIGURE_EXTS = {".png", ".jpg", ".jpeg"}
_SIDE_PREFIX = {"question": "qfig", "solution": "sfig"}


def list_figures(qdir: str | Path) -> list[Path]:
    """Image files in figures/, excluding helper files (underscore prefix)."""
    figs = Path(qdir) / "figures"
    if not figs.is_dir():
        return []
    return sorted(
        p for p in figs.iterdir()
        if p.is_file() and p.suffix.lower() in FIGURE_EXTS
        and not p.name.startswith("_")
    )


def figure_side(name: str) -> str:
    """'question' | 'solution' | 'legacy' by filename prefix."""
    n = name.lower()
    if n.startswith("qfig"):
        return "question"
    if n.startswith("sfig"):
        return "solution"
    return "legacy"


def referencing_tex(qdir: str | Path, name: str) -> list[str]:
    """Which of question.tex / solution.tex reference this figure."""
    qdir = Path(qdir)
    hits = []
    for which, fname in (("question", "question.tex"),
                         ("solution", "solution.tex")):
        tex = (qdir / fname).read_text(encoding="utf-8") \
            if (qdir / fname).is_file() else ""
        if f"figures/{name}" in tex:
            hits.append(which)
    return hits


def next_figure_name(qdir: str | Path, side: str) -> str:
    """First free qfigN.png / sfigN.png (N >= 1)."""
    prefix = _SIDE_PREFIX[side]
    taken = {p.name for p in list_figures(qdir)}
    n = 1
    while f"{prefix}{n}.png" in taken:
        n += 1
    return f"{prefix}{n}.png"


def insert_figure_ref(tex: str, filename: str) -> str:
    """Append a centered includegraphics block for filename."""
    block = ("\n\\begin{center}\n"
             f"\\includegraphics[width=0.6\\linewidth]{{figures/{filename}}}\n"
             "\\end{center}\n")
    return tex.rstrip("\n") + "\n" + block


def remove_figure_refs(tex: str, filename: str) -> tuple[str, int]:
    """Drop includegraphics lines for filename; eat a lone center env too.

    Returns (new_tex, removed_line_count).
    """
    lines = tex.split("\n")
    keep: list[str] = []
    removed = 0
    i = 0
    while i < len(lines):
        if f"figures/{filename}" in lines[i] and "includegraphics" in lines[i]:
            removed += 1
            prev_idx = next((j for j in range(len(keep) - 1, -1, -1)
                             if keep[j].strip()), None)
            nxt = next((l for l in lines[i + 1:] if l.strip()), "")
            if (prev_idx is not None and keep[prev_idx].strip() == "\\begin{center}"
                    and nxt.strip() == "\\end{center}"):
                del keep[prev_idx:]  # drop \begin{center} + any blank filler
                i += 1
                while i < len(lines) and lines[i].strip() != "\\end{center}":
                    i += 1
                i += 1  # skip the \end{center} too
                continue
            i += 1
            continue
        keep.append(lines[i])
        i += 1
    return "\n".join(keep), removed


def crop_image_file(path: str | Path, box: tuple[float, float, float, float],
                     rotate: float = 0.0) -> None:
    """Crop an image file in place; box = (l, t, r, b) fractions in [0, 1].

    `rotate` is optional clockwise degrees in [0, 360], applied AFTER the
    crop (so the box always refers to the image as displayed). 0 = no-op.
    Raises ValueError on degenerate boxes or out-of-range rotation.
    Cannot grow beyond the raster.
    """
    l, t, r, b = (min(max(v, 0.0), 1.0) for v in box)
    if r - l < 0.01 or b - t < 0.01:
        raise ValueError("crop box too small (need left<right, top<bottom)")
    try:
        deg = float(rotate)
    except (TypeError, ValueError):
        raise ValueError("rotate must be degrees in [0, 360]")
    if not 0.0 <= deg <= 360.0:
        raise ValueError("rotate must be degrees in [0, 360]")
    p = Path(path)
    img = Image.open(p).convert("RGB")
    w, h = img.size
    cropped = img.crop((int(l * w), int(t * h),
                        max(int(r * w), int(l * w) + 1),
                        max(int(b * h), int(t * h) + 1)))
    if deg:
        # PIL rotates counter-clockwise; negate for clockwise degrees.
        cropped = cropped.rotate(-deg, expand=True, fillcolor=(255, 255, 255))
    cropped.save(p, format=img.format or "PNG")
    _record_mode(p.parent, p.name, "manual")


def _record_mode(figures_dir, filename: str, mode: str) -> None:
    """Persist figure provenance sidecar (see tools_extractor). Best-effort."""
    import json
    from pathlib import Path as _P

    try:
        sidecar = _P(figures_dir) / "_modes.json"
        modes = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
        modes[str(filename)] = mode
        sidecar.write_text(json.dumps(modes, indent=1), encoding="utf-8")
    except Exception:
        pass


def save_uploaded_figure(qdir: str | Path, filename: str, data: bytes) -> Path:
    """Validate bytes are an image and save under figures/. No overwrite."""
    if Path(filename).name != filename or Path(filename).suffix.lower() not in FIGURE_EXTS:
        raise ValueError(f"bad filename: {filename!r} (need name.png/.jpg)")
    dest = Path(qdir) / "figures" / filename
    if dest.exists():
        raise ValueError(f"{filename} already exists -- pick another name")
    try:
        Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise ValueError("upload is not a readable image")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    _record_mode(dest.parent, filename, "manual")
    return dest
