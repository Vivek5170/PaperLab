"""Figure post-processing: tiny border peepings + loose whitespace.

Runs ONCE per paper after ALL extraction is complete (no AI involved):
every saved qfig*/sfig* PNG is (1) cleared of small ink components that
touch the image border (peeping text slivers, cut-off neighbor stubs --
never the diagram itself, see guards), then (2) tightly trimmed of excess
white margin, side by side, only where secure.

Guards (why the diagram itself can never be harmed):
- Only components TOUCHING the image border are candidates. A correct
  crop keeps content off the border (FIGURE STANDARD test 3), so anything
  touching it already violates the standard.
- Area cap: component pixels <= _PEEP_MAX_PX (400) AND <= 0.2% of image
  area. A wire intentionally exiting the figure stays connected to the
  figure's ink mass (tens of thousands of px) and is always kept.
- Still-touching-but-big components are left alone and REPORTED.
- Whitespace trim applies per side, only when that side has more than
  _TRIM_MARGIN px of whitespace AND no ink within 2px of the border
  (never trims into content). Never upscales, never below 32px.

Usage:
    python3 postprocess_figures.py <paper_id> [--outputs DIR] [--report-only]
"""

from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

_PEEP_MAX_PX = 400  # border component cap (absolute)
_PEEP_MAX_FRAC = 0.002  # ... and relative to image area
_TRIM_MARGIN = 10  # kept whitespace border, px
_INK_SAFE_GAP = 2  # min ink-to-border distance to allow trimming a side
_MIN_DIM = 32  # never trim a side below this size
_INK_THRESH = 128  # gray below this counts as ink


def _border_components(dark: np.ndarray) -> list:
    """Border-touching dark connected components (8-connectivity).

    Returns [{area, rows: (min, max), cols: (min, max)}]. BFS seeded from
    every dark border pixel, so interior-only ink is never even visited.
    """
    h, w = dark.shape
    seen = np.zeros_like(dark, dtype=bool)
    comps = []
    seeds = (
        [(y, x) for y in range(h) for x in (0, w - 1)]
        + [(y, x) for x in range(w) for y in (0, h - 1)]
    )
    for sy, sx in seeds:
        if not dark[sy, sx] or seen[sy, sx]:
            continue
        q = deque([(sy, sx)])
        seen[sy, sx] = True
        ys, xs = [], []
        while q:
            y, x = q.popleft()
            ys.append(y)
            xs.append(x)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if (0 <= ny < h and 0 <= nx < w and dark[ny, nx]
                            and not seen[ny, nx]):
                        seen[ny, nx] = True
                        q.append((ny, nx))
        comps.append({"area": len(ys), "rows": (min(ys), max(ys)),
                      "cols": (min(xs), max(xs)),
                      "ys": ys, "xs": xs})
    return comps


def remove_peeps(img: Image.Image) -> tuple[Image.Image, dict]:
    """Whiten small border-touching components. Returns (image, report)."""
    g = np.array(img.convert("L"))
    h, w = g.shape
    dark = g < _INK_THRESH
    cap = min(_PEEP_MAX_PX, int(h * w * _PEEP_MAX_FRAC))
    arr = np.array(img.convert("RGB"))
    removed, kept = 0, 0
    removed_px = 0
    for c in _border_components(dark):
        if c["area"] <= cap:
            # whiten EXACT component pixels only: a disconnected speck
            # sharing the bbox (e.g. a charge dot inside a C-curve) is
            # never touched.
            arr[c["ys"], c["xs"]] = 255
            removed += 1
            removed_px += c["area"]
        else:
            kept += 1
    out = Image.fromarray(arr)
    return out, {"peeps_removed": removed, "peep_px": removed_px,
                 "peeps_kept_big": kept}


def trim_whitespace(img: Image.Image,
                    margin: int = _TRIM_MARGIN) -> tuple[Image.Image, dict]:
    """Trim excess white margin per side, only where secure."""
    g = np.array(img.convert("L"))
    h, w = g.shape
    dark = g < _INK_THRESH
    if not dark.any():
        return img, {"trimmed": {}}
    ys, xs = np.where(dark)
    # secure: ink must stand off the border on a side we trim
    box = [xs.min(), ys.min(), xs.max(), ys.max()]  # x0,y0,x1,y1
    gaps = [box[0], box[1], w - 1 - box[2], h - 1 - box[3]]
    new = [0, 0, w, h]
    trimmed = {}
    for side, gap, lo, hi, size in (
            ("left", gaps[0], box[0], None, w),
            ("top", gaps[1], box[1], None, h),
            ("right", gaps[2], None, box[2], w),
            ("bottom", gaps[3], None, box[3], h)):
        if gap > margin + _INK_SAFE_GAP:
            if side in ("left", "top"):
                new_edge = lo - margin
            else:
                new_edge = hi + margin + 1
            trimmed[side] = gap - margin
        else:
            new_edge = None
        if side == "left":
            new[0] = new_edge if new_edge is not None else 0
        elif side == "top":
            new[1] = new_edge if new_edge is not None else 0
        elif side == "right":
            new[2] = new_edge if new_edge is not None else w
        else:
            new[3] = new_edge if new_edge is not None else h
    x0, y0, x1, y1 = (max(0, new[0]), max(0, new[1]),
                      min(w, new[2]), min(h, new[3]))
    if x1 - x0 < _MIN_DIM or y1 - y0 < _MIN_DIM:
        return img, {"trimmed": {}}
    if (x0, y0, x1, y1) == (0, 0, w, h):
        return img, {"trimmed": {}}
    return img.crop((x0, y0, x1, y1)), {"trimmed": trimmed}


def postprocess_file(path: str | Path) -> dict:
    """Peep removal, then whitespace trim. Overwrites the file in place."""
    p = Path(path)
    img = Image.open(p).convert("RGB")
    before = img.size
    img, rep = remove_peeps(img)
    img, trep = trim_whitespace(img)
    rep.update(trep)
    rep["before"] = before
    rep["after"] = img.size
    img.save(p, format="PNG")
    rep["file"] = p.name
    return rep


def postprocess_paper(paper_id: int, output_base=None,
                      report_only: bool = False) -> dict:
    """All qfig*/sfig* PNGs of one paper. Returns {file: report}."""
    if output_base is None:
        import directory_manager
        output_base = directory_manager.OUTPUT_BASE
    root = Path(output_base) / str(paper_id)
    out = {}
    for fig in sorted(root.glob("*/figures/*.png")):
        name = fig.name
        if not (name.startswith("qfig") or name.startswith("sfig")):
            continue
        if report_only:
            img = Image.open(fig).convert("RGB")
            _, rep = remove_peeps(img)
            _, trep = trim_whitespace(img)
            rep.update(trep)
            rep["file"] = name
            out[str(fig)] = rep
            continue
        out[str(fig)] = postprocess_file(fig)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_id", type=int)
    ap.add_argument("--outputs", default=None)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    rep = postprocess_paper(args.paper_id, args.outputs,
                            report_only=args.report_only)
    n_peep = sum(r.get("peeps_removed", 0) for r in rep.values())
    n_trim = sum(1 for r in rep.values() if r.get("trimmed"))
    print(f"{len(rep)} figures: {n_peep} peepings removed, "
          f"{n_trim} trimmed")
    for f, r in rep.items():
        if r.get("peeps_removed") or r.get("trimmed") or r.get(
                "peeps_kept_big"):
            print(f"  {Path(f).parent.name}/{r.get('file')}: {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
