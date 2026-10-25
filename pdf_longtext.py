"""Long-text stripping for figure-verification (Crop Lab definition, vector-safe).

Removes what Crop Lab calls "long text" but never figure labels:
  - decision: text LINE with > ``_VEC_TRIM_WORDS`` (3) words (same as
    ``tools_extractor._long_text_rects``) -- line-level, so a 1-word label
    merged by PyMuPDF into a stem BLOCK is still kept;
  - label guard: a long-line word within ``_VEC_LABEL_NEAR`` (10 pt) of a
    non-chrome stroke is a diagram label (``f = 10 cm``, ``D = 40 cm``,
    ``u0``) and is kept -- mirrors the assist trimmer;
  - removal: tight word rects only (no fat block boxes), ``fill=None``,
    ``apply_redactions(images=NONE, graphics=NONE, text=REMOVE)``.

Usage:
    from pdf_longtext import strip_long_text
    strip_long_text("in.pdf", "out.pdf")
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import fitz  # PyMuPDF

import re

import tools_extractor as te


def _long_block_numbers(page, chrome_t: set) -> set[int]:
    """Kept for compat: 0-based block indices that are long-text."""
    raw_blocks = page.get_text("blocks")
    long_nos: set[int] = set()
    for i, b in enumerate(raw_blocks):
        txt = str(b[4])
        if not txt.strip():
            continue
        norm = re.sub(r"\d+", "#", " ".join(txt.split()))
        fp = (round(b[0], 1), round(b[1], 1), round(b[2], 1),
              round(b[3], 1), norm)
        if fp in chrome_t:
            continue
        if len(txt.split()) > te._VEC_TRIM_WORDS:
            long_nos.add(i)
    return long_nos


def _strip_targets(page, strokes: list, aggressive: bool = False) -> list:
    """Tight word rects to delete: long-line words NOT near figure strokes.

    aggressive=True also deletes SHORT-line (<=3 words) debris far from any
    stroke (stem shards like "the plates", "then", equation bits on solution
    pages). Short text near strokes (labels) is always kept. Boundaries and
    table grids are strokes themselves and are never touched.
    """
    lines: dict = defaultdict(list)
    for w in page.get_text("words"):
        if str(w[4]).strip():
            lines[(w[5], w[6])].append(w)
    out = []
    for ws in lines.values():
        long_line = len(ws) > te._VEC_TRIM_WORDS
        for w in ws:
            r = fitz.Rect(w[0], w[1], w[2], w[3])
            if r.width <= 0 or r.height <= 0:
                continue
            near = any(te._touches(r, st, tol=te._VEC_LABEL_NEAR)
                       for st in strokes)
            if long_line and near:
                continue  # diagram label sitting on ink, keep
            if not long_line and (near or not aggressive):
                continue  # short label kept; debris only in aggressive mode
            out.append(fitz.Rect(r.x0 - 0.3, r.y0 - 0.3, r.x1 + 0.3, r.y1 + 0.3))
    return out


def strip_long_text(input_pdf_path: str | Path, output_pdf_path: str | Path,
                    fill=None, aggressive: bool = False) -> dict:
    """Strip Crop-Lab long text. Returns {"pages", "words_removed"}."""
    import fitz  # local import to keep module import light
    src = str(input_pdf_path)
    doc = fitz.open(src)
    words_removed = 0
    try:
        for pno, page in enumerate(doc, start=1):
            strokes, _, _ = te._page_vectors(src, pno)
            targets = _strip_targets(page, strokes, aggressive=aggressive)
            for rr in targets:
                page.add_redact_annot(rr, fill=fill)
            if targets:
                page.apply_redactions(
                    images=fitz.PDF_REDACT_IMAGE_NONE,
                    graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                    text=fitz.PDF_REDACT_TEXT_REMOVE)
                words_removed += len(targets)
    finally:
        pass
    doc.save(str(output_pdf_path), garbage=4, deflate=True)
    doc.close()
    return {"pages": len(fitz.open(str(output_pdf_path))), "words_removed": words_removed}


def best_for_cropping(input_pdf_path: str | Path, output_pdf_path: str | Path,
                      aggressive: bool = False) -> dict:
    """pdf_clean.py + long-text strip = best canvas for figure cropping."""
    import tempfile
    import pdf_clean as pc

    with tempfile.TemporaryDirectory() as tmp:
        cleaned = str(Path(tmp) / "cleaned.pdf")
        clean_rep = pc.clean_pdf_canvas(str(input_pdf_path), cleaned)
        strip_rep = strip_long_text(cleaned, output_pdf_path,
                                    aggressive=aggressive)
    return {"clean": clean_rep, "strip": strip_rep}
