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

# Minimum bbox-vs-embedded-image overlap that counts as "the same figure".
SNAP_IOU = 0.5
# ...or the request box contains at least this fraction of ONE image, as
# long as the box is not absurdly larger than the image itself.
SNAP_COVERAGE = 0.8
SNAP_MAX_BOX_RATIO = 5.0

# Per-PDF memo caches (keyed by resolved abspath; PDFs are treated as stable).
_CHROME_CACHE: dict[str, set[int]] = {}  # pdf -> xrefs repeating on most pages
_SNAP_CACHE: dict[tuple[str, int], tuple[str, bytes]] = {}  # (pdf, xref) -> (ext, bytes)

# Per-figure snap record for run reports: (paper_id, question_number,
# filename, "snap:<xref>" | "plain"). In-process only.
SNAP_LOG: list[tuple] = []


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
) -> tuple[str, bytes] | None:
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


def _pil_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _render_page_to_file(pdf_path: str, page_number: int, dpi: int = _RENDER_DPI) -> Path:
    """Render a page to a stable PNG path (byte-stable for identical inputs)."""
    key = hashlib.md5(f"{pdf_path}|{page_number}|{dpi}".encode()).hexdigest()
    _RENDER_CACHE.mkdir(parents=True, exist_ok=True)
    out = _RENDER_CACHE / f"{key}.png"
    if not out.exists():
        _render_page_to_pil(pdf_path, page_number, dpi).save(str(out), format="PNG")
    return out


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
    """Crop a polygonal figure from a PDF page into the question's figures/.

    Points MUST be normalized to a 1000x1000 grid over the rendered page:
    (0, 0) is TOP-LEFT, (1000, 1000) is BOTTOM-RIGHT. Example middle box:
    [(250, 200), (750, 200), (750, 800), (250, 800)]. Values are integers in
    [0, 1000]; the tool scales them to actual pixels internally. Emit 3+
    points in clockwise order (see the page image first, it arrives in the
    message after get_page_image).

    If the box closely overlaps an embedded figure image -- IoU >= 0.5, or
    the box contains >= 80% of exactly one embedded image while staying
    under 5x that image's area -- the image's ORIGINAL bytes are saved: no
    re-render blur, no cut edges, no leaked neighbors. Otherwise a plain
    crop of the rendered page is used. Either way the image is saved to
    Outputs/{paper_id}/{question_number}/figures/{output_filename} (folders
    created as needed). A preview image arrives in the next message. To fix
    a bad crop, call again with the SAME paper_id, question_number and
    output_filename plus corrected points -- the file is overwritten.

    Args:
        pdf_path: Filesystem path to the PDF file.
        page_number: 1-based page number containing the figure.
        points: List of (x, y) vertices on the 0-1000 grid.
        output_filename: e.g. "fig1.png" (single filename, no paths).
            Reuse the SAME name to correct.
        paper_id: Integer PK from LangGraph state; never invent one.
        question_number: STRING matching the submit_question call
            ("1", "15a", "15-17_paragraph"); never cast to int.
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

    img = _render_page_to_pil(pdf_path, page_number, _RENDER_DPI)
    w, h = img.size
    # Scale 0-1000 grid -> actual pixels.
    px_pts = [(x / 1000.0 * w, y / 1000.0 * h) for x, y in norm_pts]

    xs = [p[0] for p in px_pts]
    ys = [p[1] for p in px_pts]
    left, upper = max(int(min(xs)), 0), max(int(min(ys)), 0)
    right, lower = min(int(max(xs)), w), min(int(max(ys)), h)
    if right <= left or lower <= upper:
        raise ValueError("polygon has zero area after scaling to pixels")

    qdir = directory_manager.ensure_question_dir(paper_id, question_number)
    dest = qdir / directory_manager.FIGURES_DIR / filename

    snapped = _try_snap(pdf_path, page_number, norm_pts)
    snap_xref: int | None = None
    if snapped is not None:
        ext, data, snap_xref = snapped
        if _ext_matches(filename, ext):
            dest.write_bytes(data)
        else:
            try:
                Image.open(io.BytesIO(data)).convert("RGB").save(str(dest), format="PNG")
            except Exception:
                snapped = None  # fall through to plain crop
                snap_xref = None
    if snapped is None:
        # Plain crop fallback: polygon mask at full-page size, then crop
        # both image and mask to the bbox. White background outside polygon.
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).polygon(px_pts, fill=255)
        cropped = img.crop((left, upper, right, lower))
        mask_cropped = mask.crop((left, upper, right, lower))
        background = Image.new("RGB", cropped.size, (255, 255, 255))
        background.paste(cropped, mask=mask_cropped)
        background.save(str(dest), format="PNG")

    SNAP_LOG.append(
        (paper_id, str(question_number), filename,
         f"snap:{snap_xref}" if snapped is not None else "plain")
    )
    how = (
        f"Snapped to embedded image xref {snap_xref} (original bytes). "
        if snapped is not None
        else "Plain crop of the rendered page. "
    )
    return image_reply(
        tool_call_id,
        f"Saved {filename} to {dest}. {how}"
        "A preview is in the next message; inspect it before moving on.",
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
    \\includegraphics[width=\\linewidth]{figures/fig1.png}.

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
        if not (
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
    correct). Empty input or exactly "no_solution_found" saves
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
    if not content.strip() or content.strip() == "no_solution_found":
        content = directory_manager.SOLUTION_PLACEHOLDER
    else:
        errs: list[str] = []
        first = content.strip().splitlines()[0]
        if not re.search(r"[A-D]|\d", first):
            errs.append("first line must contain the final answer key")
        for f in re.findall(r"figures/([\w\-\.]+)", content):
            if not (
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
