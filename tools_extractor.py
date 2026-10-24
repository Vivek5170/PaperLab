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
import re
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

# ---- assisted_crop tuning (all PDF points unless noted) ----
CHROME_MIN_PAGES = 3  # a stroke/text fingerprint on >= this many pages is chrome
_VEC_TOUCH = 2.0  # stroke rects within this count as touching (clustering)
_VEC_SEARCH_MARGIN = 40.0  # clusters are only considered this far outside the box
_VEC_TRIM_WORDS = 3  # text blocks longer than this are trim candidates
_VEC_PAD = 0.0  # no padding: the reported box is rendered exactly
_VEC_LABEL_NEAR = 10.0  # short text within this of a stroke is a label (kept)
_VEC_GROW_CAP = 3.0  # max final/agent area ratio; beyond this growth is refused
_MIN_REPORT_DELTA = 3  # 0-1000 units below this are rounding noise, unreported
_CROP_DPI = 250  # clip-render resolution for assisted/polygon crops
_ASSIST_MAX_ATTEMPTS = 3

# Per-PDF chrome fingerprints (keyed by resolved abspath; PDFs treated as stable).
_CHROME_STROKES: dict[str, set[tuple]] = {}  # pdf -> {(x0,y0,x1,y1) rounded}
_CHROME_TEXT: dict[str, set[tuple]] = {}  # pdf -> {(rect, normalized text)}
# Per-page vector cache: (pdf, pageno) -> (stroke rects, text blocks, clusters).
_PAGE_VEC_CACHE: dict[tuple[str, int], tuple[list, list, list]] = {}
# assisted_crop attempt counter: (paper_id, question, filename) -> calls made.
_ASSIST_ATTEMPTS: dict[tuple[int, str, str], int] = {}


def reset_assist_attempts(paper_id: int | None = None) -> int:
    """Drop cached attempt counters; call at run start so reruns start fresh.

    With paper_id, resets only that paper's figures; without, resets all.
    Returns the number of counters dropped.
    """
    if paper_id is None:
        n = len(_ASSIST_ATTEMPTS)
        _ASSIST_ATTEMPTS.clear()
        return n
    doomed = [k for k in _ASSIST_ATTEMPTS if k[0] == paper_id]
    for k in doomed:
        del _ASSIST_ATTEMPTS[k]
    return len(doomed)


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
    """PDF-points rect -> 0-1000 grid ints (top-left origin)."""
    return [
        int(round(rect.x0 / page_rect.width * 1000)),
        int(round(rect.y0 / page_rect.height * 1000)),
        int(round(rect.x1 / page_rect.width * 1000)),
        int(round(rect.y1 / page_rect.height * 1000)),
    ]


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
    """Snap a 0-1000 polygon bbox to an embedded figure image, if any.

    Converts the polygon's bounding box to PDF points and returns the
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

    Call this to SEE the page before emitting polygon coordinates or
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


@tool
def polygon_crop(
    pdf_path: str,
    page_number: int,
    points: list[tuple[int, int]],
    output_filename: str,
    paper_id: int,
    question_number: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Crop EXACTLY the given polygon -- no snapping, no adjustment, no assist.

    The escape hatch when assisted_crop keeps getting it wrong: what you draw
    is what gets saved (polygon mask at 250 DPI, white background outside).
    Nothing about this call changes between retries, so it cannot loop.
    Overwriting the SAME output_filename replaces the file.

    Args:
        pdf_path: Filesystem path to the PDF file.
        page_number: 1-based page number containing the figure.
        points: List of (x, y) vertices on the 0-1000 grid.
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
    # Normalize points: LangChain may deliver lists instead of tuples.
    norm_pts = [(int(x), int(y)) for x, y in points]
    if len(norm_pts) < 3:
        raise ValueError("polygon_crop requires at least 3 points")
    for x, y in norm_pts:
        if not (0 <= x <= 1000 and 0 <= y <= 1000):
            raise ValueError(f"point {(x, y)} outside 0-1000 grid")

    doc = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(
                f"page_number {page_number} out of range 1..{len(doc)}"
            )
        r = doc[page_number - 1].rect
        fxs = [x / 1000.0 * r.width for x, _ in norm_pts]
        fys = [y / 1000.0 * r.height for _, y in norm_pts]
        if max(fxs) <= min(fxs) or max(fys) <= min(fys):
            raise ValueError("polygon has zero area after scaling to points")
        clip = fitz.Rect(min(fxs), min(fys), max(fxs), max(fys)) & r
        pix = doc[page_number - 1].get_pixmap(dpi=_CROP_DPI, clip=clip)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()

    # Polygon mask in clip-local pixels. White background outside polygon.
    cw, ch = img.size
    px_pts = [
        (
            (x / 1000.0 * r.width - clip.x0) / clip.width * cw,
            (y / 1000.0 * r.height - clip.y0) / clip.height * ch,
        )
        for x, y in norm_pts
    ]
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).polygon(px_pts, fill=255)
    background = Image.new("RGB", (cw, ch), (255, 255, 255))
    background.paste(img, mask=mask)

    qdir = directory_manager.ensure_question_dir(paper_id, question_number)
    dest = qdir / directory_manager.FIGURES_DIR / filename
    background.save(str(dest), format="PNG")

    _record_figure_mode(dest.parent, filename, "exact")
    SNAP_LOG.append((paper_id, str(question_number), filename, "exact"))
    return image_reply(
        tool_call_id,
        f"Saved {filename} to {dest}. Pure crop of exactly your box "
        "(no snapping, no adjustment). A preview is in the next message.",
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
        # The strip being cut away must hold no figure ink: that is exactly
        # the condition under which trimming cannot slice the figure.
        probe = fitz.Rect(x0, y0, x1, y1)
        return not any(_touches(probe, s, 0.0) for s in ink)

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
    points: list[tuple[int, int]],
    output_filename: str,
    paper_id: int,
    question_number: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Crop a figure with small automatic corrections. Call this FIRST.

    Your box is the intent; the tool only fixes what it can prove:
    snap -- the box matches one embedded image, so the ORIGINAL bytes are
      saved (no re-render blur, no cut edges).
    vector -- non-chrome pen strokes touching the box complete clipped shapes
      and long text lines at the edges are trimmed (short labels stay).
    plain -- no image and no strokes found; your box is saved as-is.
    The reply states the mode, your box, the final box (0-1000), a
    plain-language change list, and the attempt count. Max 3 assisted calls
    per figure; the 4th saves nothing and tells you to use polygon_crop.

    Args:
        pdf_path: Filesystem path to the PDF file.
        page_number: 1-based page number containing the figure.
        points: List of (x, y) vertices on the 0-1000 grid.
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
    # Normalize points: LangChain may deliver lists instead of tuples.
    norm_pts = [(int(x), int(y)) for x, y in points]
    if len(norm_pts) < 3:
        raise ValueError("assisted_crop requires at least 3 points")
    for x, y in norm_pts:
        if not (0 <= x <= 1000 and 0 <= y <= 1000):
            raise ValueError(f"point {(x, y)} outside 0-1000 grid")

    akey = (paper_id, str(question_number), filename)

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
            raise ValueError("polygon has zero area after scaling to points")
        page_rect = fitz.Rect(page.rect)
    finally:
        doc.close()

    # Count the attempt only after all input validation passed, so a bad
    # page number or degenerate box doesn't burn one of the three.
    attempt = _ASSIST_ATTEMPTS.get(akey, 0) + 1
    if attempt > _ASSIST_MAX_ATTEMPTS:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "attempt limit reached (3 assisted calls for this "
                        "figure). Nothing was saved. Use polygon_crop with "
                        "your own coordinates.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )
    _ASSIST_ATTEMPTS[akey] = attempt

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
            f"original image returned. Your box was {want1000}. {tag}. "
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
        # Render from the REPORTED box (not the float internals), so the
        # saved pixels match the coordinates exactly and feeding them back
        # reproduces this result byte-for-byte (idempotent).
        rep = fitz.Rect(
            final1000[0] / 1000 * page_rect.width,
            final1000[1] / 1000 * page_rect.height,
            final1000[2] / 1000 * page_rect.width,
            final1000[3] / 1000 * page_rect.height,
        )
        render_box = _inflate(rep, _VEC_PAD) & page_rect
        _clip_render_to_pil(pdf_path, page_number, render_box).save(
            str(dest), format="PNG"
        )
        _record_figure_mode(dest.parent, filename, "vector")
        SNAP_LOG.append((paper_id, str(question_number), filename, "vector"))
        return image_reply(
            tool_call_id,
            "mode: vector. your box: %s. final box: %s. changes: %s. %s. "
            "Preview attached." % (want1000, final1000, change_txt, tag),
            f"[Crop preview: {filename}]",
            dest,
            CROP_PX,
        )

    # Nothing found: plain crop of the box, said plainly.
    _clip_render_to_pil(pdf_path, page_number, want & page_rect).save(
        str(dest), format="PNG"
    )
    _record_figure_mode(dest.parent, filename, "plain")
    SNAP_LOG.append((paper_id, str(question_number), filename, "plain"))
    return image_reply(
        tool_call_id,
        "mode: plain, no image or strokes found, saved your box as-is. "
        "your box: %s. %s. Preview attached." % (want1000, tag),
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
def submit_question(paper_id: int, question_number: str, latex_content: str) -> str:
    """Compile-check and save a question. Nothing is saved if errors are returned.

    Writes ``latex_content`` to Outputs/{paper_id}/{question_number}/
    question.tex and creates/updates the questions-table row (status 'draft'
    on insert). Resubmitting the SAME question_number overwrites -- use that
    to correct mistakes. Reference cropped figures with a relative path, e.g.
    \\includegraphics[width=\\linewidth]{figures/qfig1.png} (question-side
    crops only; sfig* references are rejected).

    Args:
        paper_id: Integer PK from LangGraph state; never invent one.
        question_number: STRING ("1", "15a", "15-17_paragraph").
        latex_content: LaTeX source for the question.

    Returns:
        "saved" on success, or "NOT SAVED:\\n..." listing every problem
        (missing figure files, LaTeX errors). Fixes: correct and resubmit
        with the SAME question_number. Raises for an unknown paper_id.
    """
    if database.get_paper(paper_id) is None:
        raise ValueError(
            f"paper_id {paper_id} does not exist; "
            "it must come from pre-flight registration via LangGraph state"
        )
    errs: list[str] = []
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
                "INSERT INTO questions (paper_id, question_number, latex_folder, status)"
                " VALUES (?, ?, ?, 'draft')",
                (paper_id, str(question_number), str(qdir)),
            )
        else:
            conn.execute(
                "UPDATE questions SET latex_folder = ? WHERE id = ?",
                (str(qdir), row["id"]),
            )
        conn.commit()
    finally:
        conn.close()
    return "saved"


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
        errs: list[str] = []
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
        verdict = verify_latex_syntax.invoke({"latex_string": content})
        if verdict != "Valid":
            errs.append(verdict)
        if errs:
            return "NOT SAVED:\n" + "\n".join(errs)

    qdir = directory_manager.ensure_question_dir(paper_id, question_number)
    (qdir / directory_manager.SOLUTION_TEX).write_text(content, encoding="utf-8")
    return "saved"
