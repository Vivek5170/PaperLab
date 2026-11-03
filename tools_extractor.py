"""Phase 2 (Extractor) vision + LaTeX submission tools.

Image channel: page renders and crop previews travel as typed ``image_url``
content parts in a HumanMessage that follows each tool result (Version 2:
this endpoint rejects image blocks inside tool messages). Tool results
themselves are short text only, so history stays small and prefix-cache
stable. Previews are downscaled at creation (never afterward), and every
encoding is byte-stable for a given input.

- ``paper_id`` comes from LangGraph state (pre-flight registration). Use it
  verbatim; never invent one.
- ``question_number`` is always a STRING ("15a", "15-17_paragraph").
- All writes overwrite: to correct a mistake, resubmit with the SAME
  ``question_number`` / ``output_filename``.
- The submit tools compile-check first: nothing is saved when errors are
  returned -- fix and resubmit.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Annotated

import fitz  # PyMuPDF
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command
from PIL import Image, ImageDraw

import database
import directory_manager

_RENDER_DPI = 200

# Preview budgets: pages stay readable, crop previews are small from birth.
PAGE_PX, CROP_PX = 1600, 600
_PREVIEW_JPEG_Q = 80
_ENC_CACHE = Path("/tmp/enc")
_RENDER_CACHE = Path("/tmp/physics_pages")
# Disk caches are content-keyed and unbounded by design; cap the file count
# so /tmp cannot grow forever across runs (oldest entries go first).
_CACHE_FILE_CAP = 1000


def _prune_cache(cache_dir: Path, keep: int = _CACHE_FILE_CAP) -> None:
    """Delete oldest files beyond `keep`; best-effort, never raises."""
    try:
        files = sorted(cache_dir.glob("*"), key=lambda p: p.stat().st_mtime)
        for stale in files[: max(0, len(files) - keep)]:
            try:
                if stale.is_file():
                    stale.unlink()
            except OSError:
                pass
    except OSError:
        pass

# Minimum bbox-vs-embedded-image overlap that counts as "the same figure".
SNAP_IOU = 0.5
# ...or the request box contains at least this fraction of ONE image, as
# long as the box is not absurdly larger than the image itself.
SNAP_COVERAGE = 0.8
SNAP_MAX_BOX_RATIO = 5.0

# Per-PDF memo caches (keyed by resolved abspath; PDFs are treated as stable).
_CHROME_CACHE: dict[str, set[int]] = {}  # pdf -> xrefs repeating on most pages
_SNAP_CACHE: dict[tuple[str, int], tuple[str, bytes, int]] = {}  # (pdf, xref) -> (ext, bytes, xref)

# Per-figure snap record for run reports: (paper_id, question_number,
# filename, "snap:<xref>" | "vector" | "plain" | "exact"). In-process only.
SNAP_LOG: list[tuple] = []


def _counts_path(paper_id: int, question_number: str) -> Path:
    """Sidecar holding this question's assisted_crop attempt counts."""
    return (
        directory_manager.get_question_dir(paper_id, question_number)
        / directory_manager.FIGURES_DIR
        / _ASSIST_COUNTS_NAME
    )


def _assist_attempt(paper_id: int, question_number: str, filename: str) -> int:
    """Atomically bump and return the 1-based attempt number for a figure.

    Crash-safe: temp-file + os.replace, so a killed process never leaves a
    half-written count. Corrupt sidecars reset to empty (fail-open, same as
    a fresh figure) rather than blocking the run.
    """
    sidecar = _counts_path(paper_id, question_number)
    with _ASSIST_LOCK:
        counts: dict = {}
        try:
            if sidecar.is_file():
                loaded = json.loads(sidecar.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    counts = loaded
        except Exception:
            counts = {}
        attempt = int(counts.get(filename, 0)) + 1
        counts[filename] = attempt
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(sidecar.parent), prefix="_assist_counts", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(counts, f)
            os.replace(tmp, sidecar)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return attempt


def _assist_used(paper_id: int, question_number: str, filename: str) -> int:
    """Attempt count WITHOUT incrementing (for the exact_crop gate)."""
    try:
        loaded = json.loads(
            _counts_path(paper_id, question_number).read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return int(loaded.get(filename, 0))
    except Exception:
        pass
    return 0


# Polygon is a last resort: refuse until the figure has this many assisted
# attempts. Lower than _ASSIST_MAX_ATTEMPTS (5) on purpose -- three honest
# tries are enough signal; beyond that the agent is burning tokens.
_POLYGON_MIN_ASSIST = 3

# Anti-clip backstop (exact paths only: exact_crop + assisted-plain). The model
# speaks integers 0-1000; fractions live here alone. Any edge touching dark
# ink grows by _EDGE_INK_STEP units per round, up to _EDGE_INK_MAX per edge.
# Small on purpose: a backstop, not autopilot -- gross misses stay the
# model's job via the preview loop, and the cap doubles as the
# infinite-wire handler (a wire still touches at cap: accept and stop).
_EDGE_INK_STEP = 0.1
_EDGE_INK_MAX = 25.0
_EDGE_INK_THRESH = 128  # gray below this counts as content ink
_EDGE_CHECK_DPI = 150  # check renders: a passing edge means ~6px of
_EDGE_CHECK_DEPTH = 3  # visible gap at final render DPI, past AA fringe


def reset_assist_attempts(paper_id: int | None = None) -> int:
    """Delete persisted attempt counters; call at run start so reruns start fresh.

    With paper_id, resets only that paper's figures; without, resets every
    paper under the outputs tree. Returns the number of counters dropped.
    """
    if paper_id is None:
        base = directory_manager.paper_dir("__probe__").parent
        roots = [p for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
    else:
        roots = [directory_manager.paper_dir(paper_id)]
    dropped = 0
    with _ASSIST_LOCK:
        for root in roots:
            if not root.is_dir():
                continue
            for qdir in root.iterdir():
                sidecar = qdir / directory_manager.FIGURES_DIR / _ASSIST_COUNTS_NAME
                if not sidecar.is_file():
                    continue
                try:
                    loaded = json.loads(sidecar.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        dropped += len(loaded)
                except Exception:
                    pass
                try:
                    sidecar.unlink()
                except OSError:
                    pass
    return dropped

# ---- assisted_crop tuning (all PDF points unless noted) ----
CHROME_MIN_PAGES = 3  # a stroke/text fingerprint on >= this many pages is chrome
_VEC_TOUCH = 2.0  # stroke rects within this count as touching (clustering)
_VEC_SEARCH_MARGIN = 40.0  # clusters are only considered this far outside the box
_VEC_TRIM_WORDS = 3  # text blocks longer than this are trim candidates
_VEC_PAD = 0.0  # no padding: the reported box is rendered exactly
_VEC_LABEL_NEAR = 10.0  # short text within this of a stroke is a label (kept)
_VEC_GROW_CAP = 3.0  # max final/agent area ratio; beyond this growth is refused
_MIN_REPORT_DELTA = 3  # 0-1000 units below this are rounding noise, unreported
_CROP_DPI = 250  # clip-render resolution for assisted/exact crops
# Disk-save resolution for the same crops. The LLM preview path is
# untouched (img_block thumbnails to CROP_PX either way), so the model
# sees exactly what it saw before -- only the file on disk gets denser.
_SAVE_DPI = 600
_ASSIST_MAX_ATTEMPTS = 5

# Attempt counts live on disk (figures/_assist_counts.json per question), not
# in process memory: stateless across restarts, threads and reruns. One lock
# guards the read-modify-write so concurrent figures can't lose increments.
# Portable by design: pathlib paths, stdlib lock, temp-file + os.replace
# (atomic on both Windows and macOS) -- no fcntl, no POSIX-only calls.
_ASSIST_LOCK = threading.Lock()
_ASSIST_COUNTS_NAME = "_assist_counts.json"

# Per-PDF chrome fingerprints (keyed by resolved abspath; PDFs treated as stable).
_CHROME_STROKES: dict[str, set[tuple]] = {}  # pdf -> {(x0,y0,x1,y1) rounded}
_CHROME_TEXT: dict[str, set[tuple]] = {}  # pdf -> {(rect, normalized text)}
# Per-page vector cache: (pdf, pageno) -> (stroke rects, text blocks, clusters).
_PAGE_VEC_CACHE: dict[tuple[str, int], tuple[list, list, list]] = {}


def _pdf_key(pdf_path: str) -> str:
    return str(Path(pdf_path).resolve())


def _stroke_fp(rect) -> tuple:
    """Fingerprint a stroke by rounded position and size."""
    return (
        round(rect.x0, 1),
        round(rect.y0, 1),
        round(rect.x1, 1),
        round(rect.y1, 1),
    )


def _block_fp(block) -> tuple:
    """Fingerprint a text block by rounded rect + digit-normalized text.

    Digits are masked so running heads with varying numbers ("Page 3 of 21",
    "Set 2") still match across pages; real content differs anyway.
    """
    text = " ".join(str(block[4]).split())
    text = re.sub(r"\d+", "#", text)
    return (
        round(block[0], 1),
        round(block[1], 1),
        round(block[2], 1),
        round(block[3], 1),
        text,
    )


def _chrome_for(pdf_path: str) -> tuple[set[tuple], set[tuple]]:
    """Chrome fingerprints for a PDF: strokes/text repeating on >=3 pages.

    Headers, footers, column rules, borders and watermark outlines sit at the
    same position on many pages, so they match; real figure strokes sit at
    different positions per page, so they don't. Computed once per PDF.
    """
    key = _pdf_key(pdf_path)
    if key not in _CHROME_STROKES:
        stroke_counts: dict[tuple, int] = {}
        text_counts: dict[tuple, int] = {}
        doc = fitz.open(pdf_path)
        try:
            for i in range(len(doc)):
                page = doc[i]
                seen_s, seen_t = set(), set()
                for d in page.get_drawings():
                    seen_s.add(_stroke_fp(d["rect"]))
                for b in page.get_text("blocks"):
                    if str(b[4]).strip():
                        seen_t.add(_block_fp(b))
                for fp in seen_s:
                    stroke_counts[fp] = stroke_counts.get(fp, 0) + 1
                for fp in seen_t:
                    text_counts[fp] = text_counts.get(fp, 0) + 1
        finally:
            doc.close()
        _CHROME_STROKES[key] = {
            fp for fp, c in stroke_counts.items() if c >= CHROME_MIN_PAGES
        }
        _CHROME_TEXT[key] = {
            fp for fp, c in text_counts.items() if c >= CHROME_MIN_PAGES
        }
    return _CHROME_STROKES[key], _CHROME_TEXT[key]


def _page_vectors(pdf_path: str, page_number: int) -> tuple[list, list, list]:
    """Non-chrome (stroke rects, text blocks, stroke clusters); cached per page.

    Clustering runs once over ALL page strokes; callers select the clusters
    touching their window, so a figure stroke just outside one box is still
    available to the next.
    """
    key = (_pdf_key(pdf_path), page_number)
    if key not in _PAGE_VEC_CACHE:
        chrome_s, chrome_t = _chrome_for(pdf_path)
        doc = fitz.open(pdf_path)
        try:
            page = doc[page_number - 1]
            strokes = [
                d["rect"]
                for d in page.get_drawings()
                if _stroke_fp(d["rect"]) not in chrome_s
            ]
            blocks = [
                b
                for b in page.get_text("blocks")
                if str(b[4]).strip() and _block_fp(b) not in chrome_t
            ]
        finally:
            doc.close()
        _PAGE_VEC_CACHE[key] = (strokes, blocks, _cluster_rects(strokes))
    return _PAGE_VEC_CACHE[key]


def _touches(a, b, tol: float = _VEC_TOUCH) -> bool:
    """True when rects a and b touch or overlap (within tol)."""
    return (
        a.x0 <= b.x1 + tol
        and b.x0 <= a.x1 + tol
        and a.y0 <= b.y1 + tol
        and b.y0 <= a.y1 + tol
    )


def _inflate(rect, d: float):
    """Return rect grown by d points on every side (PyMuPDF has no expand)."""
    return fitz.Rect(rect.x0 - d, rect.y0 - d, rect.x1 + d, rect.y1 + d)


def _union(a, b):
    """Manual bbox union: ``|=`` silently drops zero-area (line) rects."""
    return fitz.Rect(
        min(a.x0, b.x0), min(a.y0, b.y0), max(a.x1, b.x1), max(a.y1, b.y1)
    )


def _cluster_rects(rects: list) -> list:
    """Group rects that touch in 2D; returns [(bbox, members)] per group."""
    n = len(rects)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _touches(rects[i], rects[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict[int, list] = {}
    for i, r in enumerate(rects):
        groups.setdefault(find(i), []).append(r)
    out = []
    for members in groups.values():
        box = fitz.Rect(members[0])
        for r in members[1:]:
            box = _union(box, r)
        out.append((box, members))
    return out


def _to_1000(rect, page_rect) -> list[int]:
    """PDF-points rect -> 0-1000 grid corner ints (top-left origin)."""
    return [
        int(round(rect.x0 / page_rect.width * 1000)),
        int(round(rect.y0 / page_rect.height * 1000)),
        int(round(rect.x1 / page_rect.width * 1000)),
        int(round(rect.y1 / page_rect.height * 1000)),
    ]


def _corners_to_rect1000(x0: int, y0: int, x1: int, y1: int) -> list[int]:
    """Corner ints -> [x, y, width, height] reply form (same grid)."""
    return [x0, y0, x1 - x0, y1 - y0]


def _chrome_xrefs(pdf_path: str) -> set[int]:
    """Xrefs behaving as page chrome (headers/footers/logos): on >50% of pages."""
    key = str(Path(pdf_path).resolve())
    if key not in _CHROME_CACHE:
        doc = fitz.open(pdf_path)
        try:
            counts: dict[int, int] = {}
            n = len(doc)
            for i in range(n):
                for img in doc[i].get_images(full=True):
                    counts[img[0]] = counts.get(img[0], 0) + 1
            _CHROME_CACHE[key] = {x for x, c in counts.items() if c > n / 2}
        finally:
            doc.close()
    return _CHROME_CACHE[key]


def _try_snap(
    pdf_path: str, page_number: int, norm_pts: list[tuple[int, int]]
) -> tuple[str, bytes, int] | None:
    """Snap a 0-1000 box to an embedded figure image, if any.

    Converts the box to PDF points and returns the
    original bytes (ext, data, xref) of the embedded image in either of two cases:
    1. IoU between the box and the image rect >= SNAP_IOU (tight box), or
    2. the box contains >= SNAP_COVERAGE of exactly one image AND the box
       is at most SNAP_MAX_BOX_RATIO times the image area (generous but
       sane box around a single figure).
    Chrome xrefs (headers/footers/logos) never qualify. Returns None on any
    failure so callers fall back to a plain crop.
    """
    doc = None
    try:
        doc = fitz.open(pdf_path)
        if page_number < 1 or page_number > len(doc):
            return None
        page = doc[page_number - 1]
        r = page.rect
        xs = [x / 1000.0 * r.width for x, _ in norm_pts]
        ys = [y / 1000.0 * r.height for _, y in norm_pts]
        want = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
        if want.is_empty or want.width <= 0 or want.height <= 0:
            return None
        want_area = want.width * want.height
        chrome = _chrome_xrefs(pdf_path)
        key = str(Path(pdf_path).resolve())
        best_iou: tuple[float, int] | None = None
        covered: list[int] = []  # xrefs the box contains >= SNAP_COVERAGE of
        for img in page.get_images(full=True):
            xref = img[0]
            if xref == 0 or xref in chrome:
                continue
            for rect in page.get_image_rects(xref):
                ix0, iy0 = max(want.x0, rect.x0), max(want.y0, rect.y0)
                ix1, iy1 = min(want.x1, rect.x1), min(want.y1, rect.y1)
                inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
                if inter <= 0:
                    continue
                union = want_area + (rect.width * rect.height) - inter
                iou = inter / union if union > 0 else 0.0
                if best_iou is None or iou > best_iou[0]:
                    best_iou = (iou, xref)
                if rect.width > 0 and rect.height > 0:
                    if inter / (rect.width * rect.height) >= SNAP_COVERAGE:
                        if want_area <= SNAP_MAX_BOX_RATIO * rect.width * rect.height:
                            if xref not in covered:
                                covered.append(xref)
        target: int | None = None
        if best_iou is not None and best_iou[0] >= SNAP_IOU:
            target = best_iou[1]
        elif len(covered) == 1:
            target = covered[0]
        if target is None:
            return None
        ckey = (key, target)
        cached = _SNAP_CACHE.get(ckey)
        if cached is None:
            info = doc.extract_image(target)
            cached = (str(info.get("ext", "")), bytes(info["image"]), target)
            _SNAP_CACHE[ckey] = cached
        return cached
    except Exception:
        return None
    finally:
        if doc is not None:
            doc.close()


def _ext_matches(filename: str, ext: str) -> bool:
    suffix = Path(filename).suffix.lower().lstrip(".")
    ext = ext.lower()
    if ext in ("jpg", "jpeg"):
        return suffix in ("jpg", "jpeg")
    return bool(suffix) and suffix == ext


def _render_page_to_pil(pdf_path: str, page_number: int, dpi: int = _RENDER_DPI) -> Image.Image:
    """Render a 1-based PDF page to a PIL RGB image at the requested DPI."""
    doc = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(
                f"page_number {page_number} out of range 1..{len(doc)}"
            )
        zoom = dpi / 72.0
        pix = doc[page_number - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def _clip_render_to_pil(
    pdf_path: str, page_number: int, clip, dpi: int = _CROP_DPI
) -> Image.Image:
    """Render just a page region (PDF points) -- lighter than a full page."""
    doc = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(
                f"page_number {page_number} out of range 1..{len(doc)}"
            )
        pix = doc[page_number - 1].get_pixmap(dpi=dpi, clip=fitz.Rect(clip))
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def _render_page_to_file(pdf_path: str, page_number: int, dpi: int = _RENDER_DPI) -> Path:
    """Render a page to a stable PNG path (byte-stable for identical inputs)."""
    key = hashlib.md5(f"{pdf_path}|{page_number}|{dpi}".encode()).hexdigest()
    _RENDER_CACHE.mkdir(parents=True, exist_ok=True)
    out = _RENDER_CACHE / f"{key}.png"
    if not out.exists():
        _render_page_to_pil(pdf_path, page_number, dpi).save(str(out), format="PNG")
        _prune_cache(_RENDER_CACHE)
    return out


def _record_figure_mode(figures_dir, filename: str, mode: str) -> None:
    """Persist figure provenance for the PaperLab reader's color tags.

    Sidecar figures/_modes.json maps filename -> snap | vector | plain |
    exact | manual. Underscore-prefixed, so figure listers skip it.
    Best-effort: never breaks a save.
    """
    import json

    try:
        sidecar = Path(figures_dir) / "_modes.json"
        modes = (
            json.loads(sidecar.read_text(encoding="utf-8"))
            if sidecar.is_file()
            else {}
        )
        modes[str(filename)] = mode
        sidecar.write_text(json.dumps(modes, indent=1), encoding="utf-8")
    except Exception:
        pass


def img_block(path: str | Path, max_side: int, q: int = _PREVIEW_JPEG_Q) -> dict:
    """Encode a file as an ``image_url`` content block (cached, byte-stable).

    The cache key derives from the file's BYTES (not its path), so the same
    content always yields identical output -- while an overwritten file
    (same path, new bytes, e.g. a corrected crop) correctly produces a
    fresh preview instead of a stale cached one.
    """
    raw = Path(path).read_bytes()
    key = hashlib.md5(raw + f"|{max_side}|{q}".encode()).hexdigest()
    _ENC_CACHE.mkdir(parents=True, exist_ok=True)
    cached = _ENC_CACHE / f"{key}.jpg"
    if not cached.exists():
        im = Image.open(path).convert("RGB")
        im.thumbnail((max_side, max_side))
        im.save(cached, "JPEG", quality=q)
        _prune_cache(_ENC_CACHE)
    b64 = base64.b64encode(cached.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def image_reply(
    tool_call_id: str, text: str, caption: str, path: str | Path, max_side: int
) -> Command:
    """Text-only ToolMessage first, then the image as a normal user message."""
    return Command(
        update={
            "messages": [
                ToolMessage(text, tool_call_id=tool_call_id),
                HumanMessage(
                    content=[
                        {"type": "text", "text": caption},
                        img_block(path, max_side),
                    ]
                ),
            ]
        }
    )


@tool
def get_page_image(
    pdf_path: str,
    page_number: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Render a PDF page. The page image arrives in the next message.

    Call this to SEE the page before emitting box coordinates or
    transcribing LaTeX.

    Args:
        pdf_path: Filesystem path to the PDF file.
        page_number: 1-based page number.
    """
    out = _render_page_to_file(pdf_path, page_number, _RENDER_DPI)
    return image_reply(
        tool_call_id,
        f"Page {page_number} of {pdf_path} rendered at {out}. "
        "The image is in the next message.",
        f"[Image: {pdf_path} page {page_number}]",
        out,
        PAGE_PX,
    )


def _touching_ink(pix) -> tuple:
    """Per edge (left, top, right, bottom): (touches_ink, dark_px_count).

    Band = _EDGE_CHECK_DEPTH px at check DPI, so a passing edge guarantees
    several clean pixels (not a sub-pixel graze) at final render DPI.
    """
    w, h, n = pix.width, pix.height, pix.n
    d = _EDGE_CHECK_DEPTH
    if w < 2 * d or h < 2 * d or n < 3:
        return [False] * 4, [0] * 4
    s = pix.samples

    def is_dark(x, y):
        i = (y * w + x) * n
        return (s[i] + s[i + 1] + s[i + 2]) // 3 < _EDGE_INK_THRESH

    zones = [
        [(x, y) for x in range(d) for y in range(h)],
        [(x, y) for x in range(w) for y in range(d)],
        [(x, y) for x in range(w - d, w) for y in range(h)],
        [(x, y) for x in range(w) for y in range(h - d, h)],
    ]
    counts = [sum(1 for x, y in z if is_dark(x, y)) for z in zones]
    return [c > 0 for c in counts], counts


_EDGE_NAMES = ["left", "top", "right", "bottom"]



def _expand_box_for_ink(page, box: list, max_pad: float = _EDGE_INK_MAX) -> tuple:
    """Grow a 0-1000 float box past edge-touching ink.

    The page this runs on is the figure-only crop canvas (long text
    truly deleted, vector/raster intact), so there is no text veto at
    all: +_EDGE_INK_STEP units per touching edge per round, max +max_pad
    per edge. Returns (expanded_box, pads, capped, cut): `capped` = still
    touching at the max with nothing beyond (terminating content);
    `cut` = edge slices through content continuing outside (own diagram
    or neighbor's). Unsolved edges (capped/cut) are reverted to the
    requested position -- no partial extension is kept -- so the saved
    preview honestly shows the cut and follow-up numbers anchor on the
    model's own box.
    """
    r = page.rect
    pads = [0.0, 0.0, 0.0, 0.0]
    touched = [False] * 4

    def pts(b):
        return fitz.Rect(
            b[0] / 1000 * r.width, b[1] / 1000 * r.height,
            b[2] / 1000 * r.width, b[3] / 1000 * r.height,
        ) & r

    for _ in range(int(max_pad / _EDGE_INK_STEP) + 1):
        b = [
            max(0.0, box[0] - pads[0]), max(0.0, box[1] - pads[1]),
            min(1000.0, box[2] + pads[2]), min(1000.0, box[3] + pads[3]),
        ]
        pix = page.get_pixmap(dpi=_EDGE_CHECK_DPI, clip=pts(b))
        touched, _counts = _touching_ink(pix)
        if not any(touched):
            return b, [round(p, 1) for p in pads], [], []  # RET-A
        grew = False
        for i, on in enumerate(touched):
            if not on or pads[i] >= max_pad - 1e-9:
                continue
            pads[i] = min(max_pad, pads[i] + _EDGE_INK_STEP)
            grew = True
        if not grew:
            break
    # Final classification render (one render; consistent basis for all
    # verdicts below).
    pix = page.get_pixmap(dpi=_EDGE_CHECK_DPI, clip=pts(b))
    touched, _counts = _touching_ink(pix)
    if not any(touched):
        return b, [round(p, 1) for p in pads], [], []  # RET-A
    maxed = [i for i, on in enumerate(touched)
             if on and pads[i] >= max_pad - 1e-9]
    if not maxed:
        # Touching but neither capped nor cuttable (e.g. growth stalled):
        # report as still-cut so the model looks at it.
        left_idx = [i for i, on in enumerate(touched) if on]
        left = [_EDGE_NAMES[i] for i in left_idx]
        for i in left_idx:
            pads[i] = 0.0  # no partial extension on unsolved edges
        b = [
            max(0.0, box[0] - pads[0]), max(0.0, box[1] - pads[1]),
            min(1000.0, box[2] + pads[2]), min(1000.0, box[3] + pads[3]),
        ]
        return b, [round(p, 1) for p in pads], left, []
    # Capped/exhausted while still touching: check whether content continues
    # beyond the edge (cut through: own diagram or neighbor's) or
    # terminates there (wire end). One extra render; rare path only.
    outside = _outside_ink(page, b)
    cut = [_EDGE_NAMES[i] for i in maxed if outside[i]]
    capped = [_EDGE_NAMES[i] for i in maxed if not outside[i]]
    for i in maxed:
        pads[i] = 0.0  # no partial extension on unsolved edges: the saved
        # preview honestly shows the cut and hints anchor on your numbers
    b = [
        max(0.0, box[0] - pads[0]), max(0.0, box[1] - pads[1]),
        min(1000.0, box[2] + pads[2]), min(1000.0, box[3] + pads[3]),
    ]
    return b, [round(p, 1) for p in pads], capped, cut


def _outside_ink(page, box: list, margin_units: float = 8.0) -> list:
    """Per edge: dark ink just OUTSIDE the box (a lookahead band).

    Together with edge-touching ink inside, this means the edge cuts
    through content continuing outside -- own diagram or neighbor's, the
    model must judge from the preview.
    """
    r = page.rect
    c = [max(0.0, box[0] - margin_units), max(0.0, box[1] - margin_units),
         min(1000.0, box[2] + margin_units),
         min(1000.0, box[3] + margin_units)]
    clip = fitz.Rect(c[0] / 1000 * r.width, c[1] / 1000 * r.height,
                     c[2] / 1000 * r.width, c[3] / 1000 * r.height) & r
    if clip.is_empty:
        return [False] * 4
    pix = page.get_pixmap(dpi=_EDGE_CHECK_DPI, clip=clip)
    w, h, n = pix.width, pix.height, pix.n
    d = _EDGE_CHECK_DEPTH
    if w < 2 * d or h < 2 * d or n < 3:
        return [False] * 4
    s = pix.samples

    def px(u, v):
        return (int((u / 1000 * r.width - clip.x0) / clip.width * w),
                int((v / 1000 * r.height - clip.y0) / clip.height * h))

    def is_dark(x, y):
        if not (0 <= x < w and 0 <= y < h):
            return False
        i = (y * w + x) * n
        return (s[i] + s[i + 1] + s[i + 2]) // 3 < _EDGE_INK_THRESH

    x0, _ = px(box[0], 0)
    x1, _ = px(box[2], 0)
    _, y0 = px(0, box[1])
    _, y1 = px(0, box[3])
    return [
        any(is_dark(x, y) for x in range(x0 - d, x0) for y in range(h)),
        any(is_dark(x, y) for x in range(w) for y in range(y0 - d, y0)),
        any(is_dark(x, y) for x in range(x1, x1 + d) for y in range(h)),
        any(is_dark(x, y) for x in range(w) for y in range(y1, y1 + d)),
    ]


_EDGE_PARAM = {"left": ("x", "decrease"), "top": ("y", "decrease"),
                "right": ("width", "increase"),
                "bottom": ("height", "increase")}

# Thinking-procedure Step 2 rules, spelled out per edge (must match
# prompts/extractor_prompt.md Step 2a-2d verbatim).
_STEP2_RULES = {
    "left": "Step 2a -- LEFT edge: diagram clipped there -- decrease x; "
            "junk or foreign text there -- increase x.",
    "top": "Step 2b -- TOP edge: diagram clipped there -- decrease y; "
           "junk or foreign text there -- increase y.",
    "right": "Step 2c -- RIGHT edge: diagram clipped there -- increase "
             "width; junk or foreign text there -- decrease width.",
    "bottom": "Step 2d -- BOTTOM edge: diagram clipped there -- increase "
              "height; junk or foreign text there -- decrease height.",
}


def _edge_clearance(page, b, i, max_units=25.0):
    """How far ink continues past edge i (0-1000 units), failure path only.

    Renders one band outside the edge and takes the FARTHEST line that
    still holds ink (>=2 dark px, so AA fringe and stray specks don't
    count). Farthest-not-first-gap matters: dotted content (text glyphs:
    ink, gap, ink...) would otherwise report one glyph width instead of
    the true span. Returns (units_or_None, nearest_word_or_None): None
    units = ink reaches the band end (runs deeper than max_units); the
    word is the nearest text-layer word in that band (a shrink hint --
    foreign text -- vs plain ink the model must judge from the preview).
    """
    r = page.rect
    wpt = max_units / 1000 * (r.width if i in (0, 2) else r.height)
    cur = fitz.Rect(b[0] / 1000 * r.width, b[1] / 1000 * r.height,
                    b[2] / 1000 * r.width, b[3] / 1000 * r.height)
    band = {0: fitz.Rect(cur.x0 - wpt, cur.y0, cur.x0, cur.y1),
            1: fitz.Rect(cur.x0, cur.y0 - wpt, cur.x1, cur.y0),
            2: fitz.Rect(cur.x1, cur.y0, cur.x1 + wpt, cur.y1),
            3: fitz.Rect(cur.x0, cur.y1, cur.x1, cur.y1 + wpt)}[i] & r
    if band.is_empty:
        return None, None
    try:
        pix = page.get_pixmap(dpi=_EDGE_CHECK_DPI * 2, clip=band)
    except Exception:
        return None, None
    w, h, n = pix.width, pix.height, pix.n
    if w < 2 or h < 2 or n < 3:
        return None, None
    s = pix.samples

    def dark(x, y):
        j = (y * w + x) * n
        return (s[j] + s[j + 1] + s[j + 2]) // 3 < _EDGE_INK_THRESH

    span = w if i in (0, 2) else h
    across = h if i in (0, 2) else w

    def at(k, p):
        # k = steps outward from the edge, p = position along the edge
        if i == 0:
            return (w - 1 - k, p)
        if i == 2:
            return (k, p)
        if i == 1:
            return (p, h - 1 - k)
        return (p, k)

    def line_dark(k):
        # a line counts as ink with >=2 dark px (fringe/speck tolerant)
        return sum(1 for p in range(across) if dark(*at(k, p))) >= 2

    best = None
    for k in range(span):
        if line_dark(k):
            best = k
    if best is None:
        return 0.0, None  # probe sees nothing: a ~2u nudge suffices
    if best >= span - 1:
        units = None  # ink reaches the band end: deeper than max_units
    else:
        units = best / span * max_units
    word = None
    try:
        best = None
        for wd in page.get_text("words"):
            if not str(wd[4]).strip():
                continue
            wr = fitz.Rect(wd[:4])
            if not wr.intersects(band):
                continue
            gap = {0: cur.x0 - wr.x1, 1: cur.y0 - wr.y1,
                   2: wr.x0 - cur.x1, 3: wr.y0 - cur.y1}[i]
            gapu = max(0.0, gap / (r.width if i in (0, 2) else r.height)
                       * 1000)
            if best is None or gapu < best[1]:
                best = (str(wd[4]).strip(), gapu)
        word = best
    except Exception:
        word = None
    return units, word


def _fix_hints(page, grown, capped, cut,
               max_pad=_EDGE_INK_MAX) -> dict:
    """Per-edge fix sentences for capped/cut edges (failure paths).

    Tool measures, model judges: grow numbers assume the content out there
    is the model's own diagram; the caution says the tool suggests extending
    even for a neighbor's figure. Returns {edge: sentence}. Page open.
    """
    tips = {}
    for e in list(capped) + [x for x in cut if x not in capped]:
        i = _EDGE_NAMES.index(e)
        try:
            d, word = _edge_clearance(page, grown, i)
        except Exception:
            continue
        if d is None:
            d = 25.0  # deeper than the probe band: quote it as a lower bound
        p, op = _EDGE_PARAM[e]
        idx = {"x": 0, "y": 1, "width": 2, "height": 3}[p]
        # grown is corners: width/height suggestions must be sizes,
        # not the x1/y1 corner (that bug quoted ~908 for a 259-wide box)
        if p == "width":
            cur = grown[2] - grown[0]
        elif p == "height":
            cur = grown[3] - grown[1]
        else:
            cur = grown[idx]
        val = cur - (d + 2.0) if op == "decrease" else cur + d + 2.0
        rule = _STEP2_RULES[e]
        if e in cut:
            first = (f"{e} edge cuts through content continuing outside the "
                     f"box. Nothing is extended on this side (edge kept at "
                     f"your {p}) because extension doesn't solve it -- the "
                     f"saved crop still cuts there.")
        else:
            first = (f"{e} edge: grew the max (+{max_pad:.1f}) and it still "
                     f"touches content -- extension doesn't solve it, so "
                     f"nothing is extended on this side (edge kept at your "
                     f"{p}) and the saved crop still cuts there.")
        tip = (f"{first} Fix it yourself per {rule} Measured: ink runs "
               f"~{d:.0f}u past the edge -- {op} {p} by ~{d + 2.0:.0f}u "
               f"(e.g. {p} approx {val:.0f}). Caution: this number assumes "
               f"the content out there is your diagram; if your box caught "
               f"a different figure, the tool still suggests extending to "
               f"include it -- shrink past it instead.")
        if word:
            tip += f" Nearest text {word[0]!r} ~{word[1]:.0f}u out."
        tips[e] = tip
    return tips


def _pad_note(pads, capped=(), cut=(), final=None,
              hints=None) -> str:
    """Lite reply fragment reporting auto-expansion (model-facing).

    `final` is the grown box in reply units: corrections must anchor on
    it -- tighten an edge by resubmitting that side strictly inside the
    final numbers, loosen by going beyond them. Never guess from scratch.
    `hints` is the per-edge dict from _fix_hints; edges missing from it
    fall back to generic sentences (same Step 2 rule, no numbers).
    """
    grown = [f"{n}+{p:.1f}" for n, p in zip(_EDGE_NAMES, pads) if p > 0]
    if not grown and not cut and not capped:
        return ""
    hints = hints or {}
    anchor = ""
    needs_fix = bool(capped or cut)
    if final is not None:
        anchor = (" Correct from the final box %s: tighten an edge by "
                  "resubmitting that side strictly inside these numbers, "
                  "loosen by going beyond them. Per-edge numbers below are "
                  "auto-measured from the page by fixed rules, not "
                  "judgments -- verify against the preview and decide "
                  "yourself."
                  % (list(final),))
    note = ""
    if grown:
        note += (" Auto-expanded %s to clear edge-touching ink."
                 % ", ".join(grown))
    if not needs_fix:
        note += (" Edges now clear. New box is %s (format [x, y, width, "
                 "height]). If the preview is not a perfect figure, "
                 "correct it using thinking-procedure Step 2."
                 % (list(final) if final is not None else [],))
        return note
    note += anchor
    for e in cut:
        note += " " + hints.get(e, (
            f"{e} edge cuts through content continuing outside the box. "
            f"Nothing is extended on this side (edge kept at your "
            f"{_EDGE_PARAM[e][0]}) because extension doesn't solve it -- "
            f"the saved crop still cuts there. Fix it yourself per "
            f"{_STEP2_RULES[e]} Caution: this assumes the content out "
            f"there is your diagram; if your box caught a different "
            f"figure, shrink past it instead."))
    for e in capped:
        note += " " + hints.get(e, (
            f"{e} edge: grew the max and it still touches content -- "
            f"extension doesn't solve it, so nothing is extended on this "
            f"side (edge kept at your {_EDGE_PARAM[e][0]}) and the saved "
            f"crop still cuts there. Fix it yourself per "
            f"{_STEP2_RULES[e]}"))
    return note + " Resubmit."


@tool
def exact_crop(
    pdf_path: str,
    page_number: int,
    x: int,
    y: int,
    width: int,
    height: int,
    output_filename: str,
    paper_id: int,
    question_number: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Crop exactly the given rectangle: what you draw is what gets saved.

    Last resort: refuses until the same file already has 3 assisted_crop
    attempts. You may call this multiple times with corrected
    coordinates; reuse the SAME output_filename (it overwrites).

    Your box is (x, y, width, height): integers 0-1000, top-left origin.
    Fractions are truncated -- keep sending ints, never floats. Every box
    in and out of every crop tool is [x, y, width, height] -- replies echo
    your box and the final box in the same form, never corners. Adjust per
    the prompt's Step 2a-2d (which edge is bad -> which parameter moves
    which way); every bad edge's reply spells out its exact rule plus
    measured numbers.

    The tool itself may expand edges by fractions of a unit (up to 25)
    where dark ink touches the border, and says so in the reply --
    "edges now clear" means done, "still cut" means move the edge
    yourself per the Step 2 rule named in the reply. If the preview shows
    unintended text seeping in, redraw that edge to fully exclude the
    text and resubmit, anchoring on the final box numbers -- the pad only
    fires on ink touching the edge, so a clean edge stays put.

    Correction suggestions in replies are mechanical rules of thumb
    (which edge looks bad -> which parameter to move), not judgments
    about your figure: the tool cannot tell your diagram from a
    neighbor's figure or an intentional wire exit. Always verify against
    the preview and decide yourself -- where a suggestion and the FIGURE
    STANDARD disagree, the STANDARD wins.

    Args:
        pdf_path: Filesystem path to the PDF file.
        page_number: 1-based page number containing the figure.
        x: Left edge, integer 0-1000.
        y: Top edge, integer 0-1000.
        width: Box width in grid units (x + width <= 1000).
        height: Box height in grid units (y + height <= 1000).
        output_filename: e.g. "qfig1.png" (single filename, no paths).
        paper_id: Integer PK from LangGraph state; never invent one.
        question_number: STRING matching the submit_question call.
    """
    if database.get_paper(paper_id) is None:
        raise ValueError(
            f"paper_id {paper_id} does not exist; "
            "it must come from pre-flight registration via LangGraph state"
        )
    filename = directory_manager.safe_component(output_filename, "output_filename")
    # Integers only: truncate, never round up (rounding up could push an
    # edge onto neighboring text).
    x, y, width, height = (int(v) for v in (x, y, width, height))
    # Figure-only canvas: detection AND save see the crop canvas (long
    # text truly deleted, vector/raster intact), never the raw page.
    # Lazy import: pdf_longtext imports this module at its top level.
    from pdf_longtext import ensure_crop_canvas
    pdf_path = ensure_crop_canvas(pdf_path)
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        raise ValueError(f"top-left {(x, y)} outside 0-1000 grid")
    if width < 1 or height < 1:
        raise ValueError("width and height must be at least 1")
    if x + width > 1000 or y + height > 1000:
        raise ValueError("box must fit inside the 0-1000 grid")
    norm_pts = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]

    # Last-resort gate: cheap plain refusal (no preview burned) that
    # redirects to assisted_crop, where snap-matching runs.
    tried = _assist_used(paper_id, str(question_number), filename)
    if tried < _POLYGON_MIN_ASSIST:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"exact_crop refused: {tried} of "
                        f"{_POLYGON_MIN_ASSIST} required assisted_crop "
                        f"attempts used for {filename}. Call assisted_crop "
                        f"({_POLYGON_MIN_ASSIST - tried} tries left) with a "
                        "tighter box first; snap-matching only runs there.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    # Exact-only: no snap-matching here by design (it runs solely inside
    # assisted_crop). What you draw is what gets saved, byte for byte.
    qdir = directory_manager.ensure_question_dir(paper_id, question_number)
    dest = qdir / directory_manager.FIGURES_DIR / filename

    hints = ""
    doc = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(
                f"page_number {page_number} out of range 1..{len(doc)}"
            )
        page = doc[page_number - 1]
        r = page.rect
        fxs = [x / 1000.0 * r.width for x, _ in norm_pts]
        fys = [y / 1000.0 * r.height for _, y in norm_pts]
        if max(fxs) <= min(fxs) or max(fys) <= min(fys):
            raise ValueError("box has zero area after scaling to points")
        # Anti-clip: expand the bbox past edge-touching ink (0.1-unit
        # steps, max 25 per edge), then map the box corners onto it.
        # Fractions stay inside this tool; the model keeps sending ints.
        bx = [float(min(f[0] for f in norm_pts)),
              float(min(f[1] for f in norm_pts)),
              float(max(f[0] for f in norm_pts)),
              float(max(f[1] for f in norm_pts))]
        grown, pads, capped, cut = (
            _expand_box_for_ink(page, bx)
            if (bx[2] > bx[0] and bx[3] > bx[1])
            else (bx, [0.0] * 4, [], [])
        )
        hints = (_fix_hints(page, grown, capped, cut)
                 if (capped or cut) else {})
        sx = ((grown[2] - grown[0]) / (bx[2] - bx[0])
              if bx[2] > bx[0] else 1.0)
        sy = ((grown[3] - grown[1]) / (bx[3] - bx[1])
              if bx[3] > bx[1] else 1.0)
        fpts = [
            (grown[0] + (x - bx[0]) * sx, grown[1] + (y - bx[1]) * sy)
            for x, y in norm_pts
        ]
        fxs = [x / 1000.0 * r.width for x, _ in fpts]
        fys = [y / 1000.0 * r.height for _, y in fpts]
        clip = fitz.Rect(min(fxs), min(fys), max(fxs), max(fys)) & r
        pix = page.get_pixmap(dpi=_SAVE_DPI, clip=clip)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()

    # Rect mask in clip-local pixels. White background outside the box.
    cw, ch = img.size
    px_pts = [
        (
            (x / 1000.0 * r.width - clip.x0) / clip.width * cw,
            (y / 1000.0 * r.height - clip.y0) / clip.height * ch,
        )
        for x, y in fpts
    ]
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).polygon(px_pts, fill=255)
    background = Image.new("RGB", (cw, ch), (255, 255, 255))
    background.paste(img, mask=mask)

    background.save(str(dest), format="PNG")

    _record_figure_mode(dest.parent, filename, "exact")
    SNAP_LOG.append((paper_id, str(question_number), filename, "exact"))
    your1000 = [int(min(f[0] for f in norm_pts)),
                int(min(f[1] for f in norm_pts)),
                int(max(f[0] for f in norm_pts)),
                int(max(f[1] for f in norm_pts))]
    final1000 = [int(round(v)) for v in grown]
    return image_reply(
        tool_call_id,
        f"Saved {filename} to {dest}. Exact crop of your box. "
        f"your box: {_corners_to_rect1000(*your1000)}. "
        f"final box: {_corners_to_rect1000(*final1000)} (boxes are "
        f"[x, y, width, height])."
        + _pad_note(pads, capped, cut,
                      final=_corners_to_rect1000(*final1000),
                      hints=hints)
        + " A preview is in the next message.",
        f"[Crop preview: {filename}]",
        dest,
        CROP_PX,
    )


def _assist_box(
    page, want, blocks: list, clusters: list
) -> tuple | None:
    """Vector-assist the agent's box; None when no stroke cluster is near it.

    Clusters touching the window join the box to a fixed point (feeding the
    result back changes nothing); long text blocks crossing a box edge or
    sitting fully inside it are trimmed (short labels stay). Growth beyond
    _VEC_GROW_CAP x the agent's area is refused. Returns
    (final_rect_unpadded, [(edge, snippet)], capped_box_or_None).
    """
    window = _inflate(want, _VEC_SEARCH_MARGIN)
    sel = [(c, m) for c, m in clusters if _touches(c, window, 0.0)]
    if not sel:
        return None
    box = fitz.Rect(want)
    # Fixed-point union: any selected cluster touching the box joins it.
    for _ in range(25):
        grown = fitz.Rect(box)
        for c, _m in sel:
            if _touches(c, box):
                grown = _union(grown, c)
        if (grown.x0, grown.y0, grown.x1, grown.y1) == (
            box.x0,
            box.y0,
            box.x1,
            box.y1,
        ):
            break
        box = grown
    else:
        box = grown
    if not any(_touches(c, box) for c, _m in sel):
        return None

    if box.width * box.height > _VEC_GROW_CAP * want.width * want.height:
        return fitz.Rect(want), [], fitz.Rect(box), []

    included = [r for c, m in sel if _touches(c, box) for r in m]
    changes: list[tuple] = []

    def trimmable(b) -> bool:
        # Word count + distance only. Short text survives solely as a label
        # hugging the figure; stray question fragments far from every stroke
        # are trimmed like the rest.
        rect = (b[0], b[1], b[2], b[3])
        words = str(b[4]).split()
        if len(words) > _VEC_TRIM_WORDS:
            return True
        if not included:
            return False
        bx0, by0, bx1, by1 = rect
        gap = float("inf")
        for s in included:
            dx = max(s.x0 - bx1, bx0 - s.x1, 0.0)
            dy = max(s.y0 - by1, by0 - s.y1, 0.0)
            gap = min(gap, (dx * dx + dy * dy) ** 0.5)
        return gap > _VEC_LABEL_NEAR

    # Ink fully inside a trimmable text block is text decoration (underlines,
    # rules, glyph fragments), not figure: it neither vetoes trims (strip
    # check) nor anchors the shrink. A wire merely passing through keeps
    # sticking out, so it stays protected.
    zones = [(b[0], b[1], b[2], b[3]) for b in blocks if trimmable(b)]

    def in_zone(r) -> bool:
        return any(
            zx0 - 2 <= r.x0
            and zy0 - 2 <= r.y0
            and r.x1 <= zx1 + 2
            and r.y1 <= zy1 + 2
            for zx0, zy0, zx1, zy1 in zones
        )

    ink = [s for s in included if not in_zone(s)]

    def strip_empty(x0: float, y0: float, x1: float, y1: float) -> bool:
        # The strip being cut away must hold no figure ink AND no kept text:
        # slicing through a label the rules decided to keep is as bad as
        # slicing ink. (Trimmable text in the strip is simply left for its
        # own trim pass or dropped with the strip -- it never vetoes.)
        probe = fitz.Rect(x0, y0, x1, y1)
        if any(_touches(probe, s, 0.0) for s in ink):
            return False
        return not any(
            not trimmable(b)
            and _touches(probe, fitz.Rect(b[0], b[1], b[2], b[3]), 0.0)
            for b in blocks
        )

    # Text removal, unified: for every text block, each inward edge alignment
    # is one operation, whether the block crosses the edge or sits inside.
    # A trim applies iff the strip it removes holds no figure ink.
    for _ in range(10):
        moved = False
        for b in blocks:
            if not trimmable(b):
                continue
            bx0, by0, bx1, by1 = b[0], b[1], b[2], b[3]
            snippet = " ".join(str(b[4]).split())[:40]
            if box.y0 < by1 < box.y1 and strip_empty(
                box.x0, box.y0, box.x1, by1
            ):
                box.y0 = by1
                changes.append(("top", snippet))
                moved = True
                continue
            if box.y0 < by0 < box.y1 and strip_empty(
                box.x0, by0, box.x1, box.y1
            ):
                box.y1 = by0
                changes.append(("bottom", snippet))
                moved = True
                continue
            if box.x0 < bx1 < box.x1 and strip_empty(
                box.x0, box.y0, bx1, box.y1
            ):
                box.x0 = bx1
                changes.append(("left", snippet))
                moved = True
                continue
            if box.x0 < bx0 < box.x1 and strip_empty(
                bx0, box.y0, box.x1, box.y1
            ):
                box.x1 = bx0
                changes.append(("right", snippet))
                moved = True
                continue
        if not moved:
            break

    # Shrink empty margins: pull each edge in to the content (figure ink
    # and kept text inside the box), so loose space with no vectors goes.
    content = [r for r in ink if _touches(r, box, 0.0)]
    for b in blocks:
        if box.x0 <= b[0] and box.y0 <= b[1] and b[2] <= box.x1 and b[3] <= box.y1:
            content.append(fitz.Rect(b[0], b[1], b[2], b[3]))
    if content:
        cx0 = min(r.x0 for r in content)
        cy0 = min(r.y0 for r in content)
        cx1 = max(r.x1 for r in content)
        cy1 = max(r.y1 for r in content)
        if box.x0 < cx0 < box.x1:
            box.x0 = cx0
            changes.append(("left", ""))
        if box.y0 < cy0 < box.y1:
            box.y0 = cy0
            changes.append(("top", ""))
        if box.x0 < cx1 < box.x1:
            box.x1 = cx1
            changes.append(("right", ""))
        if box.y0 < cy1 < box.y1:
            box.y1 = cy1
            changes.append(("bottom", ""))

    if box.is_empty or box.width <= 0 or box.height <= 0:
        return None
    box &= page.rect
    if box.is_empty or box.width <= 0 or box.height <= 0:
        return None

    # Leftover verdicts for the Crop Lab: why each surviving text block is
    # still there. (Applied trims are already in `changes`.)
    verdicts: list[tuple] = []
    for b in blocks:
        bx0, by0, bx1, by1 = b[0], b[1], b[2], b[3]
        if not _touches(fitz.Rect(bx0, by0, bx1, by1), box, 0.0):
            continue
        snippet = " ".join(str(b[4]).split())[:60]
        words = len(str(b[4]).split())
        if not trimmable(b):
            verdicts.append((snippet, words, "kept: short label hugging ink"))
            continue
        reason = "kept: no inward edge applies"
        if box.y0 < by1 < box.y1 and not strip_empty(box.x0, box.y0, box.x1, by1):
            reason = "kept: strip above holds ink"
        elif box.y0 < by0 < box.y1 and not strip_empty(box.x0, by0, box.x1, box.y1):
            reason = "kept: strip below holds ink"
        elif box.x0 < bx1 < box.x1 and not strip_empty(box.x0, box.y0, bx1, box.y1):
            reason = "kept: strip left holds ink"
        elif box.x0 < bx0 < box.x1 and not strip_empty(bx0, box.y0, box.x1, box.y1):
            reason = "kept: strip right holds ink"
        verdicts.append((snippet, words, reason))
    return box, changes, None, verdicts


@tool
def assisted_crop(
    pdf_path: str,
    page_number: int,
    x: int,
    y: int,
    width: int,
    height: int,
    output_filename: str,
    paper_id: int,
    question_number: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Crop a figure with small automatic corrections. Call this FIRST
    for every figure; use exact_crop only when this tool refuses you.

    Your box is (x, y, width, height): integers 0-1000, top-left origin.
    x, y is the top-left corner; width, height the size. Fractions are
    truncated -- keep sending ints. Every box in and out of every crop
    tool is [x, y, width, height] -- replies echo your box and the final
    box in the same form, never corners. Adjust per the prompt's Step
    2a-2d (which edge is bad -> which parameter moves which way); every
    bad edge's reply spells out its exact rule plus measured numbers.

    Your box is the intent; the tool only fixes what it can prove:
    snap -- the box matches one embedded image, so the ORIGINAL bytes are
      saved (no re-render blur, no cut edges).
    vector -- non-chrome pen strokes touching the box complete clipped shapes
      and long text lines at the edges are trimmed (short labels stay).
    plain -- no image and no strokes found; your box is saved as-is.

    Correction suggestions in replies are mechanical rules of thumb
    (which edge looks bad -> which parameter to move), not judgments
    about your figure: the tool cannot tell your diagram from a
    neighbor's figure or an intentional wire exit. Always verify against
    the preview and decide yourself -- where a suggestion and the FIGURE
    STANDARD disagree, the STANDARD wins.
    The reply states the mode, your box, the final box, a plain-language
    change list, and the attempt count. Non-snap saves may expand edges by
    fractions of a unit where dark ink touches the border (plain up to 25
    units, vector up to 5); growth stops at the cap, and the reply says
    what happened -- "still cut" means the fix is yours, with the Step 2
    rule and a concrete number. If the preview shows unintended text
    seeping in, redraw that edge to fully exclude the text and resubmit,
    anchoring on the final box numbers -- a clean edge never regrows.

    Args:
        pdf_path: Filesystem path to the PDF file.
        page_number: 1-based page number containing the figure.
        x: Left edge, integer 0-1000.
        y: Top edge, integer 0-1000.
        width: Box width in grid units (x + width <= 1000).
        height: Box height in grid units (y + height <= 1000).
        output_filename: e.g. "qfig1.png" (single filename, no paths).
            Reuse the SAME name to correct.
        paper_id: Integer PK from LangGraph state; never invent one.
        question_number: STRING matching the submit_question call.
    """
    if database.get_paper(paper_id) is None:
        raise ValueError(
            f"paper_id {paper_id} does not exist; "
            "it must come from pre-flight registration via LangGraph state"
        )
    filename = directory_manager.safe_component(output_filename, "output_filename")
    # Integers only: LangChain may deliver floats; truncate, never round up
    # (rounding up could push an edge onto neighboring text).
    x, y, width, height = (int(v) for v in (x, y, width, height))
    # Figure-only canvas: detection AND save see the crop canvas (long
    # text truly deleted, vector/raster intact), never the raw page.
    # Lazy import: pdf_longtext imports this module at its top level.
    from pdf_longtext import ensure_crop_canvas
    pdf_path = ensure_crop_canvas(pdf_path)
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        raise ValueError(f"top-left {(x, y)} outside 0-1000 grid")
    if width < 1 or height < 1:
        raise ValueError("width and height must be at least 1")
    if x + width > 1000 or y + height > 1000:
        raise ValueError("box must fit inside the 0-1000 grid")
    norm_pts = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]

    # Count the attempt only after all input validation passed, so a bad
    # page number or degenerate box doesn't burn one of the five. The count
    # persists in figures/_assist_counts.json (per question dir), so it
    # survives restarts and is shared across threads; runs reset it.
    doc = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(
                f"page_number {page_number} out of range 1..{len(doc)}"
            )
        page = doc[page_number - 1]
        r = page.rect
        xs = [x / 1000.0 * r.width for x, _ in norm_pts]
        ys = [y / 1000.0 * r.height for _, y in norm_pts]
        want = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
        if want.is_empty or want.width <= 0 or want.height <= 0:
            raise ValueError("box has zero area after scaling to points")
        page_rect = fitz.Rect(page.rect)
    finally:
        doc.close()

    attempt = _assist_attempt(paper_id, str(question_number), filename)
    if attempt > _ASSIST_MAX_ATTEMPTS:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "attempt limit reached (5 assisted calls for this "
                        "figure). Nothing was saved. Use exact_crop with "
                        "your own x, y, width, height.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    want1000 = [
        int(round(want.x0 / r.width * 1000)),
        int(round(want.y0 / r.height * 1000)),
        int(round(want.x1 / r.width * 1000)),
        int(round(want.y1 / r.height * 1000)),
    ]
    tag = f"attempt {attempt} of {_ASSIST_MAX_ATTEMPTS}"
    qdir = directory_manager.ensure_question_dir(paper_id, question_number)
    dest = qdir / directory_manager.FIGURES_DIR / filename

    snapped = _try_snap(pdf_path, page_number, norm_pts)
    if snapped is not None:
        ext, data, snap_xref = snapped
        try:
            if _ext_matches(filename, ext):
                dest.write_bytes(data)
            else:
                Image.open(io.BytesIO(data)).convert("RGB").save(
                    str(dest), format="PNG"
                )
        except Exception:
            snapped = None
    if snapped is not None:
        _record_figure_mode(dest.parent, filename, "snap")
        SNAP_LOG.append(
            (paper_id, str(question_number), filename, f"snap:{snap_xref}")
        )
        return image_reply(
            tool_call_id,
            f"mode: snap, matched embedded image (xref {snap_xref}), "
            f"original image returned. "
            f"Your box was {_corners_to_rect1000(*want1000)} "
            f"(boxes are [x, y, width, height]). {tag}. "
            "Preview attached.",
            f"[Crop preview: {filename}]",
            dest,
            CROP_PX,
        )

    _strokes, blocks, clusters = _page_vectors(pdf_path, page_number)
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        assisted = _assist_box(page, want, blocks, clusters)
    finally:
        doc.close()

    if assisted is not None:
        final, trim_notes, capped, _verdicts = assisted
        final1000 = _to_1000(final, page_rect)
        if capped is not None:
            far1000 = _to_1000(capped, page_rect)
            change_txt = (
                "strokes continue far beyond your box (to %s); not applied. "
                "Re-crop if you want that." % (far1000,)
            )
        else:
            changes: list[str] = []
            edges = (("left", 0), ("top", 1), ("right", 2), ("bottom", 3))
            for edge, i in edges:
                delta = final1000[i] - want1000[i]
                if edge in ("left", "top"):
                    delta = -delta  # positive = box grew outward
                if delta >= _MIN_REPORT_DELTA:
                    changes.append(
                        "extended %s by %d (strokes continued past your edge)"
                        % (edge, delta)
                    )
                elif delta <= -_MIN_REPORT_DELTA:
                    changes.append("trimmed %s by %d" % (edge, -delta))
            for edge, snippet in trim_notes:
                for k, c in enumerate(changes):
                    if c.startswith("trimmed %s by" % edge) and "(text line" not in c and "(empty margin)" not in c:
                        changes[k] = c + (
                            ' (text line "%s")' % snippet
                            if snippet
                            else " (empty margin)"
                        )
                        break
            change_txt = "; ".join(changes) if changes else "no change needed"
        # Anti-clip on the vector result too (cap 5: stroke-grow already
        # did the big growing; this only fixes edge grazes, fractions stay
        # in here). The REPORTED final box is unchanged (idempotent); only
        # the render may be wider, and the reply says so.
        doc = fitz.open(pdf_path)
        try:
            vpage = doc[page_number - 1]
            vgrown, vpads, vcapped, vcut = _expand_box_for_ink(
                vpage, [float(v) for v in final1000], max_pad=5.0)
            vhints = (_fix_hints(vpage, vgrown, vcapped, vcut, max_pad=5.0)
                      if (vcapped or vcut) else {})
        finally:
            doc.close()
        rep = fitz.Rect(
            vgrown[0] / 1000 * page_rect.width,
            vgrown[1] / 1000 * page_rect.height,
            vgrown[2] / 1000 * page_rect.width,
            vgrown[3] / 1000 * page_rect.height,
        )
        render_box = _inflate(rep, _VEC_PAD) & page_rect
        _clip_render_to_pil(pdf_path, page_number, render_box,
                            dpi=_SAVE_DPI).save(
            str(dest), format="PNG"
        )
        _record_figure_mode(dest.parent, filename, "vector")
        SNAP_LOG.append((paper_id, str(question_number), filename, "vector"))
        return image_reply(
            tool_call_id,
            "mode: vector. your box: %s. final box: %s (boxes are "
            "[x, y, width, height]). changes: %s.%s %s. Preview attached."
            % (_corners_to_rect1000(*want1000),
               _corners_to_rect1000(*final1000), change_txt,
               _pad_note(vpads, vcapped, vcut,
                         final=_corners_to_rect1000(*final1000),
                         hints=vhints), tag),
            f"[Crop preview: {filename}]",
            dest,
            CROP_PX,
        )

    # Nothing found: plain crop of the box, plus the same anti-clip
    # expansion as usual (fractions stay in here; the model keeps ints).
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        grown, pads, capped, cut = _expand_box_for_ink(
            page, [float(v) for v in want1000])
        phints = (_fix_hints(page, grown, capped, cut)
                  if (capped or cut) else {})
    finally:
        doc.close()
    grown_pts = fitz.Rect(
        grown[0] / 1000 * r.width, grown[1] / 1000 * r.height,
        grown[2] / 1000 * r.width, grown[3] / 1000 * r.height,
    )
    _clip_render_to_pil(pdf_path, page_number, grown_pts & page_rect,
                        dpi=_SAVE_DPI).save(
        str(dest), format="PNG"
    )
    _record_figure_mode(dest.parent, filename, "plain")
    SNAP_LOG.append((paper_id, str(question_number), filename, "plain"))
    grown1000 = [int(round(v)) for v in grown]
    return image_reply(
        tool_call_id,
        "mode: plain, no image or strokes found, saved your box as-is. "
        "your box: %s. final box: %s (boxes are [x, y, width, height])."
        "%s %s. Preview attached."
        % (_corners_to_rect1000(*want1000),
           _corners_to_rect1000(*grown1000),
           _pad_note(pads, capped, cut,
                     final=_corners_to_rect1000(*grown1000),
                     hints=phints), tag),
        f"[Crop preview: {filename}]",
        dest,
        CROP_PX,
    )


@tool
def verify_latex_syntax(latex_string: str) -> str:
    """Check LaTeX for unbalanced braces and mismatched environments.

    Run drafted question/solution LaTeX through this BEFORE submitting; fix
    reported errors and re-verify until it returns "Valid".

    Args:
        latex_string: The LaTeX source to check.

    Returns:
        "Valid", or a "; "-separated list of syntax errors.
    """
    errors: list[str] = []

    # --- Brace matching (ignore escaped \{ \} and \\ control) ---
    # Strip escaped braces so they are not counted.
    scrubbed = latex_string.replace("\\\\", "")
    depth = 0
    for i, ch in enumerate(scrubbed):
        if ch == "\\":
            continue  # handled below via lookbehind instead
        if ch not in "{}":
            continue
        # Count preceding backslashes to detect escaping.
        j = i - 1
        n_bs = 0
        while j >= 0 and scrubbed[j] == "\\":
            n_bs += 1
            j -= 1
        if n_bs % 2 == 1:
            continue  # escaped brace
        if ch == "{":
            depth += 1
        else:
            depth -= 1
            if depth < 0:
                errors.append(f"Unmatched closing brace '}}' at position {i}")
                depth = 0
    if depth > 0:
        errors.append(f"Unmatched opening brace '{{': {depth} unclosed")

    # --- Environment matching ---
    tokens = re.findall(r"\\(begin|end)\{([^{}]+)\}", latex_string)
    stack: list[str] = []
    for kind, env in tokens:
        if kind == "begin":
            stack.append(env)
        else:  # end
            if not stack:
                errors.append(f"Stray \\end{{{env}}} with no open environment")
            elif stack[-1] != env:
                errors.append(
                    f"Mismatched environment: expected \\end{{{stack[-1]}}} "
                    f"but found \\end{{{env}}}"
                )
                # Attempt recovery: pop until match or empty.
                if env in stack:
                    while stack and stack[-1] != env:
                        errors.append(f"Unclosed \\begin{{{stack.pop()}}}")
                    stack.pop()
                # else: leave stack as-is, stray end already reported
            else:
                stack.pop()
    for env in reversed(stack):
        errors.append(f"Unclosed \\begin{{{env}}}")

    return "Valid" if not errors else "; ".join(errors)


@tool
def submit_question(paper_id: int, question_number: str, latex_content: str,
                     qtype: str = "unknown") -> str:
    """Compile-check and save a question. Nothing is saved if errors are returned.

    Writes ``latex_content`` to Outputs/{paper_id}/{question_number}/
    question.tex. Resubmitting the SAME question_number overwrites -- use
    that to correct mistakes (including a wrong qtype). Reference cropped
    figures with a relative path, e.g.
    \\includegraphics[width=\\linewidth]{figures/qfig1.png}
    (question-side crops only; sfig* references are rejected). Save also
    auto-fixes what it can: one paragraph per inline option, backtick
    unwrapping, text-mode underscore escaping.

    Question type is decided from the SECTION header first, the question
    image second, never from the transcribed tex alone:
    scq single-correct choice (A-D or i/ii/iii/iv, one correct, incl.
    Assertion-Reason/statement-sets); msq multi-correct (one or more);
    int integer 0-9 entry; num decimal/numeric entry; mtx match-table
    (List-I/II or Columns + combo options); par-scq/par-msq/par-int/
    par-num/par-mtx passage group with uniform subs; par-mix mixed subs;
    unknown when illegible or no rule fires.

    Args:
        paper_id: Integer PK from LangGraph state; never invent one.
        question_number: STRING ("1", "15a", "15-17_paragraph").
        latex_content: LaTeX source for the question.
        qtype: One of scq, msq, int, num, mtx, par-scq, par-msq,
            par-int, par-num, par-mtx, par-mix, unknown. Defaults to
            unknown -- pass explicitly whenever the section header or
            image makes it clear.

    Returns:
        "saved" on success, or "NOT SAVED:\\n..." listing every problem
        (missing figure files, LaTeX errors, bad qtype). Fixes: correct
        and resubmit with the SAME question_number. Raises for an unknown
        paper_id.
    """
    if database.get_paper(paper_id) is None:
        raise ValueError(
            f"paper_id {paper_id} does not exist; "
            "it must come from pre-flight registration via LangGraph state"
        )
    qt = str(qtype or "unknown").strip().lower()
    if qt not in database.QTYPE_VALUES:
        return ("NOT SAVED:\nbad qtype %r: must be one of %s"
                % (qtype, ", ".join(database.QTYPE_VALUES)))
    # Inline options ("A) ... B) ..." on one line) merge in both renderers
    # (single \n is a space in LaTeX and markdown). One paragraph per option
    # at save time so the PNG and the HTML agree. Hard-wrapped stems are
    # untouched: only option labels split, never arbitrary prose lines.
    from app.render import _split_inline_options as _split_q_options
    latex_content = _split_q_options(latex_content)
    latex_content = _strip_backtick_quoting(latex_content)
    latex_content = _escape_text_underscores(latex_content)
    errs: list[str] = []
    if "`" in latex_content:
        errs.append("stray backtick quoting (e.g. `k' or `$m$'): put math in "
                    "$...$ with no backticks or quote marks around it")
    for f in re.findall(r"figures/([\w\-\.]+)", latex_content):
        if f.startswith("sfig"):
            errs.append(f"solution-side figure in question: {f} -- crop it "
                        "from a question page as qfig* instead")
        elif not (
            directory_manager.get_question_dir(paper_id, question_number)
            / directory_manager.FIGURES_DIR
            / f
        ).exists():
            errs.append(f"missing figure file: {f}")
    verdict = verify_latex_syntax.invoke({"latex_string": latex_content})
    if verdict != "Valid":
        errs.append(verdict)
    if errs:
        return "NOT SAVED:\n" + "\n".join(errs)

    qdir = directory_manager.ensure_question_dir(paper_id, question_number)
    (qdir / directory_manager.QUESTION_TEX).write_text(latex_content, encoding="utf-8")

    database.init_db()
    conn = database.get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM questions WHERE paper_id = ? AND question_number = ?",
            (paper_id, str(question_number)),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO questions (paper_id, question_number, latex_folder, status, qtype)"
                " VALUES (?, ?, ?, 'draft', ?)",
                (paper_id, str(question_number), str(qdir), qt),
            )
        else:
            conn.execute(
                "UPDATE questions SET latex_folder = ?, qtype = ? WHERE id = ?",
                (str(qdir), qt, row["id"]),
            )
        conn.commit()
    finally:
        conn.close()
    return "saved"


# ------------------------------------------------------- auto-fix on save
# One unambiguous slip is corrected silently so the agent isn't forced
# into a wasted resubmit cycle. Anything ambiguous still returns NOT SAVED:
# guessing could silently corrupt content (e.g. `k' should become $k$,
# not plain k'; quotes around plain words like 'C' are legitimate prose
# and must be kept).

_MATH_SPAN_RE = re.compile(
    r"\$\$.*?\$\$|\\\[.*?\\\]|(?<!\\)\$(?:[^$\\]|\\.)*?\$", re.DOTALL)


def _escape_text_underscores(tex: str) -> str:
    """Escape bare _ outside math: ``is ___`` -> ``is \\_\\_\\_``.

    A text-mode underscore is always a LaTeX error (Missing $ inserted),
    so this fires unambiguously; math spans pass through untouched and an
    already-escaped \\_ is left alone.
    """
    out, pos = [], 0
    for m in _MATH_SPAN_RE.finditer(tex):
        out.append(re.sub(r"(?<!\\)_", r"\\_", tex[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(re.sub(r"(?<!\\)_", r"\\_", tex[pos:]))
    return "".join(out)


_BACKTICK_MATH_RE = re.compile(r"`\s*(\$[^$]+\$)\s*['`']?")


def _strip_backtick_quoting(tex: str) -> str:
    """Unwrap backtick-wrapped math: `` `$m$' `` -> ``$m$``.

    Only fires when the math is already $-delimited, so the fix is
    unambiguous. A residual backtick (`` `k' `` without delimiters) is
    left for the validator to reject -- the agent must decide it is math.
    """
    return _BACKTICK_MATH_RE.sub(r"\1", tex)


# ---------------------------------------------------------------- normalize
# One logical step per line -> paragraphs. Idempotent; skips math, lists,
# comments. Solutions only: hard-wrapped question text would split wrongly.

_MATH_ENVS = {"align", "gather", "equation", "eqnarray", "multline"}
_NORM_DELIM_RE = re.compile(
    r"\\\[|\\\]|\\(?:begin|end)\{(?:align|gather|equation|eqnarray|multline)\*?\}|\$\$"
)
_NORM_ENV_RE = re.compile(r"\\(begin|end)\{([^}]*)\}")


def _norm_math_after(line: str, in_math: bool) -> bool:
    for m in _NORM_DELIM_RE.finditer(line):
        t = m.group(0)
        if t == "$$":
            in_math = not in_math
        else:
            in_math = t == "\\[" or t.startswith("\\begin")
    return in_math


def normalize_steps(tex: str) -> str:
    """Insert a blank line between consecutive prose lines.

    Each source line is one logical step; LaTeX and markdown both treat a
    single newline as a space, so without this the steps merge. A blank line
    means the same thing (paragraph break) in both renderers, so neither
    renderer needs a workaround. Idempotent; math blocks, list items,
    comments and structural commands are left alone.
    """
    lines = [ln.rstrip() for ln in tex.split("\n")]
    out: list[str] = []
    in_math, depth = False, 0
    for i, s in enumerate(lines):
        was_math = in_math
        in_math = _norm_math_after(s, in_math)
        for m in _NORM_ENV_RE.finditer(s):
            if m.group(2).rstrip("*") in _MATH_ENVS:
                continue
            depth = max(0, depth + (1 if m.group(1) == "begin" else -1))
        out.append(s)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if (
            s.strip()
            and nxt.strip()
            and not was_math
            and not in_math
            and depth == 0
            and not s.lstrip().startswith(("%", "\\item"))
            and not s.endswith("\\\\")
            and not nxt.lstrip().startswith(("\\end", "\\item", "%"))
        ):
            out.append("")
    return "\n".join(out)


@tool
def submit_solution(paper_id: int, question_number: str, latex_content: str) -> str:
    """Compile-check and save a solution. Line 1 must contain the answer key.

    Writes ``latex_content`` to Outputs/{paper_id}/{question_number}/
    solution.tex (overwrites on resubmit -- reuse the SAME question_number to
    correct). Reference solution-side crops, e.g.
    \\includegraphics[width=\\linewidth]{figures/sfig1.png} (qfig*
    references are rejected). Empty input or exactly "no_solution_found" saves
    \\textit{No solution provided.} instead. Call submit_question for the
    question first; submitting a solution for an unknown question fails.
    Save also normalizes steps to blank-line paragraphs and auto-escapes
    text-mode underscores and backtick quoting.

    Args:
        paper_id: Integer PK from LangGraph state; never invent one.
        question_number: STRING matching the submit_question call.
        latex_content: LaTeX source with the final answer key on the first
            line, or "" / "no_solution_found" if none exists.

    Returns:
        "saved" on success, or "NOT SAVED:\\n..." listing every problem.
        Raises for an unknown paper_id or a question_number with no
        submitted question.
    """
    if database.get_paper(paper_id) is None:
        raise ValueError(
            f"paper_id {paper_id} does not exist; "
            "it must come from pre-flight registration via LangGraph state"
        )
    database.init_db()
    conn = database.get_connection()
    try:
        has_question = conn.execute(
            "SELECT id FROM questions WHERE paper_id = ? AND question_number = ?",
            (paper_id, str(question_number)),
        ).fetchone()
    finally:
        conn.close()
    if has_question is None:
        raise ValueError(
            f"No question {str(question_number)!r} submitted for paper_id {paper_id}; "
            "call submit_question first"
        )

    content = latex_content if isinstance(latex_content, str) else str(latex_content)
    stripped = content.strip()
    if not stripped or stripped.lower() == "no_solution_found":
        content = directory_manager.SOLUTION_PLACEHOLDER
    else:
        lines = stripped.split("\n")
        if len(lines) > 1:
            # Body = everything below a possible key line, minus an optional
            # leading "NN. " question-number prefix the agent sometimes adds.
            body = "\n".join(lines[1:])
            body_core = re.sub(r"^\s*\d+\s*[\.\)]\s*", "", body.strip(), count=1)
            if body_core.strip().lower() in ("", "no_solution_found"):
                # Keep the real key, mark the missing body explicitly.
                content = lines[0].rstrip() + "\n" + directory_manager.SOLUTION_PLACEHOLDER
                qdir = directory_manager.ensure_question_dir(paper_id, question_number)
                (qdir / directory_manager.SOLUTION_TEX).write_text(content, encoding="utf-8")
                return "saved"
        content = _strip_backtick_quoting(content)
        content = _escape_text_underscores(content)
        errs: list[str] = []
        if "`" in content:
            errs.append("stray backtick quoting (e.g. `k' or `$m$'): put math in "
                        "$...$ with no backticks or quote marks around it")
        first = content.strip().splitlines()[0]
        if not re.search(r"[A-D]|\d", first):
            errs.append("first line must contain the final answer key")
        for f in re.findall(r"figures/([\w\-\.]+)", content):
            if f.startswith("qfig"):
                errs.append(f"question-side figure in solution: {f} -- crop it "
                            "from a solution page as sfig* instead")
            elif not (
                directory_manager.get_question_dir(paper_id, question_number)
                / directory_manager.FIGURES_DIR
                / f
            ).exists():
                errs.append(f"missing figure file: {f}")
        content = normalize_steps(content)
        verdict = verify_latex_syntax.invoke({"latex_string": content})
        if verdict != "Valid":
            errs.append(verdict)
        if errs:
            return "NOT SAVED:\n" + "\n".join(errs)

    qdir = directory_manager.ensure_question_dir(paper_id, question_number)
    (qdir / directory_manager.SOLUTION_TEX).write_text(content, encoding="utf-8")
    return "saved"
