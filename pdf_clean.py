"""Deterministic PDF cleaning for Phase 2 (Extractor) vision.

The extractor agent sees ONLY cleaned copies: light-gray pattern
watermarks, repeating chrome images, full-page ground layers and
annotations are removed without reflowing anything, so page numbers and
0-1000 coordinates map 1:1 onto the originals.

The papers table keeps the ORIGINAL paths forever (library, archive,
pairing and Full-PDF all use those). Cleaned copies live in
``data/cleaned/`` named ``{paper_id:02d}_{source_stem}__{clean,crop}.pdf``
and are reused across reruns. Every failure falls back
to the original path -- a dirty PDF the agent can still read beats a
missing one.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

import database
import directory_manager


def _slug(stem: str) -> str:
    """Filesystem-safe slug preserving human readability of source names."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    s = re.sub(r"_+", "_", s)
    return s or "paper"


def cleaned_paths(paper_id: int, question_src: str | None,
                  solution_src: str | None):
    """Human-readable cleaned/crop-canvas paths for a paper.

    ``{id:02d}_{slug(source_stem)}__{clean,crop}.pdf`` under CLEANED_DIR.
    """
    cdir = directory_manager.CLEANED_DIR
    pre = f"{int(paper_id):02d}"
    q = f"{pre}_{_slug(Path(question_src).stem)}__clean.pdf" if question_src else None
    s = f"{pre}_{_slug(Path(solution_src).stem)}__clean.pdf" if solution_src else None
    return {
        "question_pdf": str(cdir / q) if q else None,
        "solution_pdf": str(cdir / s) if s else None,
        "question_crop_pdf": str(cdir / q).replace("__clean.pdf", "__crop.pdf") if q else None,
        "solution_crop_pdf": str(cdir / s).replace("__clean.pdf", "__crop.pdf") if s else None,
    }

# Production defaults (footer/header text redaction stays OFF: boilerplate
# text is harmless to the extractor and auto-strings risk overreach).
CHROME_MIN_PAGES = 3
BG_COVERAGE = 0.7
BG_MIN_PAGES = 2
PATTERN_GRAY = 0.6


def _chrome_images(doc, min_pages: int) -> set:
    """Xrefs of embedded images appearing on >= min_pages."""
    n = len(doc)
    img_pages: Counter = Counter()
    for p in doc:
        img_pages.update({x[0] for x in p.get_images(full=True) if x[0]})
    return {x for x, k in img_pages.items() if k >= min(min_pages, n)}


def _white_pixmap():
    px = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1, 1))
    px.clear_with(255)
    return px


def _pattern_xrefs(doc) -> dict:
    """All tiling-pattern XObjects referenced from any page's resources."""
    out = {}
    for page in doc:
        res = doc.xref_object(page.xref)
        m = re.search(r"/Pattern\s*<<(.*?)>>", res, re.S)
        if not m:
            continue
        for _name, x in re.findall(r"/(\S+?)\s+(\d+) 0 R", m.group(1)):
            out.setdefault(int(x), page.number)
    return out


_GRAY_RG_RE = re.compile(rb"(\d*\.?\d+)\s+(\d*\.?\d+)\s+(\d*\.?\d+)\s+rg")
_GRAY_G_RE = re.compile(rb"(?<![\w.])(0\.\d+|[01](?:\.\d+)?)\s+g(?![\w])")


def _gray_patterns(doc, min_gray: float = PATTERN_GRAY) -> list:
    """Coloured tiling patterns whose own stream paints light gray --
    the watermark signature. Returns [(xref, new_stream)]. Dark patterns
    (real figure hatching) are left alone."""
    found = []
    for xref in _pattern_xrefs(doc):
        try:
            obj = doc.xref_object(xref)
            raw = doc.xref_stream(xref)
        except Exception:
            continue
        if not raw or "/PaintType 1" not in obj.replace("\n", " "):
            continue  # uncoloured: colour comes from page content, not ours

        def fix_rg(m):
            try:
                vals = [float(m.group(i)) for i in (1, 2, 3)]
            except Exception:
                return m.group(0)
            return b"1 1 1 rg" if min(vals) >= min_gray else m.group(0)

        def fix_g(m):
            try:
                v = float(m.group(1))
            except Exception:
                return m.group(0)
            return b"1 g" if v >= min_gray else m.group(0)

        new = _GRAY_G_RE.sub(fix_g, _GRAY_RG_RE.sub(fix_rg, raw))
        if new != raw:
            found.append((xref, new))
    return found


def _page_backgrounds(doc, coverage: float = BG_COVERAGE,
                       safe_mode: bool = True, min_pages: int = BG_MIN_PAGES):
    """Xrefs safe to white out: every usage covers >= coverage of its page
    on >= min_pages pages (a repeating ground layer, not a one-off
    full-page figure), and -- in safe mode -- every page it sits on has a
    live text layer (so no baked-in content dies with it)."""
    usage: dict = {}  # xref -> [(pageno, covered_fraction)]
    for pi, page in enumerate(doc):
        area = page.rect.width * page.rect.height
        for img in page.get_images(full=True):
            xref = img[0]
            if not xref:
                continue
            try:
                rects = page.get_image_rects(xref) or []
            except Exception:
                continue
            frac = sum(r.width * r.height for r in rects) / area if area else 0
            usage.setdefault(xref, []).append((pi, frac))
    ok, skipped = set(), 0
    for xref, uses in usage.items():
        if len(uses) < min_pages:
            continue  # one-off: could be a legitimate full-page figure
        if not uses or not all(f >= coverage for _, f in uses):
            continue  # figure-sized somewhere: not a pure background
        if safe_mode and any(
                len(doc[pi].get_text().strip()) < 50 for pi, _ in uses):
            skipped += 1  # a usage page has no text layer: content is baked in
            continue
        ok.add(xref)
    return ok, skipped


def clean_pdf_canvas(input_pdf_path, output_pdf_path,
                     watermark_text: str = "",
                     remove_annots: bool = True, redact_text: bool = False,
                     remove_chrome_images: bool = True,
                     min_pages: int = CHROME_MIN_PAGES,
                     replace_background: bool = True, bg_safe_mode: bool = True,
                     bg_coverage: float = BG_COVERAGE,
                     bg_min_pages: int = BG_MIN_PAGES,
                     whiten_patterns: bool = True,
                     pattern_gray: float = PATTERN_GRAY) -> dict:
    """Clean one PDF; returns a report dict of what was removed where."""
    report = {"annots": 0, "text_hits": 0, "chrome_images": 0,
              "backgrounds": 0, "bg_skipped": 0, "patterns": 0,
              "chrome_skipped": 0, "pages": 0}
    doc = fitz.open(input_pdf_path)
    report["pages"] = len(doc)
    chrome_imgs = _chrome_images(doc, min_pages)

    # 0a. Pattern watermarks: light-gray tiling fills repainted white
    # inside the pattern definition. Page content is untouched.
    if whiten_patterns:
        for xref, new_stream in _gray_patterns(doc, min_gray=pattern_gray):
            try:
                doc.update_stream(xref, new_stream)
                report["patterns"] += 1
            except Exception:
                pass

    # 0b. Ground-layer background (doc-wide per xref): swap pixels for
    # white. Placement, text and vectors above it are untouched.
    if replace_background:
        white = _white_pixmap()
        ok, skipped = _page_backgrounds(doc, coverage=bg_coverage,
                                        safe_mode=bg_safe_mode,
                                        min_pages=bg_min_pages)
        report["bg_skipped"] = skipped
        for xref in ok:
            try:
                doc[0].replace_image(xref, pixmap=white)
                report["backgrounds"] += 1
            except Exception:
                report["bg_skipped"] += 1

    for page in doc:
        # 1. Delete annotations / overlays via the real API.
        if remove_annots:
            for annot in list(page.annots() or []):
                try:
                    page.delete_annot(annot)
                    report["annots"] += 1
                except Exception:
                    pass

        # 2. Watermark text redaction (opt-in: exact string required).
        if redact_text and watermark_text:
            for rect in page.search_for(watermark_text):
                page.add_redact_annot(rect, fill=(1, 1, 1))
                report["text_hits"] += 1

        # 3. Chrome images: delete just the image reference, so text and
        # vectors stacked above it survive. (Redaction would white out the
        # whole stack -- never use it for this.)
        if remove_chrome_images:
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in chrome_imgs:
                    try:
                        page.delete_image(xref)
                        report["chrome_images"] += 1
                    except Exception:
                        report["chrome_skipped"] += 1
                elif not xref:
                    report["chrome_skipped"] += 1

        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    doc.save(output_pdf_path, garbage=4, deflate=True)
    doc.close()
    return report


def _clean_one(src: str | None, dest: Path) -> tuple[str | None, dict | None]:
    """Clean one PDF, reusing the cached copy when present. Fail-open:
    any error returns (src, None) so the extractor still has a PDF."""
    if not src:
        return None, None
    if dest.is_file():
        return str(dest), {"reused": True}
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        report = clean_pdf_canvas(src, str(dest))
        return str(dest), report
    except Exception as exc:
        print(f"pdf_clean: {src} failed ({type(exc).__name__}: {exc}); "
              "extractor will use the original")
        return src, None


def clean_paper_pdfs(paper_id: int) -> dict:
    """Clean a paper's PDFs for Phase 2 vision. Returns
    {"question_pdf", "solution_pdf", "question_crop_pdf",
    "solution_crop_pdf", "reports"} with cleaned paths, or the original
    paths wherever cleaning was skipped/failed. The crop canvases hold
    ONLY figure content (chrome removed + long text stripped via true
    text-object deletion; vector/raster ink untouched) and are what the
    crop tools see. Never raises for a known paper (unknown paper_id
    still raises ValueError)."""
    from pdf_longtext import remove_chrome, strip_long_text

    row = database.get_paper(paper_id)
    if row is None:
        raise ValueError(f"paper_id {paper_id} does not exist")
    names = cleaned_paths(paper_id, row["question_pdf_path"],
                            row["solution_pdf_path"])
    cdir = directory_manager.CLEANED_DIR
    _dst = lambda n: Path(n) if n else None
    q_clean, q_rep = _clean_one(row["question_pdf_path"], _dst(names["question_pdf"]))
    s_clean, s_rep = _clean_one(row["solution_pdf_path"], _dst(names["solution_pdf"]))

    def _crop_canvas(cleaned: str | None, name: str) -> str | None:
        if not cleaned:
            return None
        dest = cdir / name
        if dest.is_file():
            return str(dest)
        try:
            nochrome = str(dest) + ".nochrome.tmp.pdf"
            remove_chrome(cleaned, nochrome)
            strip_long_text(nochrome, str(dest), aggressive=True)
            Path(nochrome).unlink(missing_ok=True)
            return str(dest) if dest.is_file() else cleaned
        except Exception as exc:
            print(f"pdf_clean: crop canvas {name} failed "
                  f"({type(exc).__name__}: {exc}); using cleaned")
            return cleaned

    q_crop = _crop_canvas(q_clean, Path(names["question_crop_pdf"]).name
                            if names["question_crop_pdf"] else None)
    s_crop = _crop_canvas(s_clean, Path(names["solution_crop_pdf"]).name
                            if names["solution_crop_pdf"] else None)
    reports = {"question": q_rep, "solution": s_rep}
    flat = {k: v for r in reports.values() if r for k, v in r.items()
            if isinstance(v, int)}
    print(f"pdf_clean: paper {paper_id} -> "
          f"{Path(q_clean).name if q_clean else None}, "
          f"{Path(s_clean).name if s_clean else None} "
          f"patterns={flat.get('patterns', 0)} "
          f"chrome={flat.get('chrome_images', 0)} "
          f"bg={flat.get('backgrounds', 0)}")
    return {"question_pdf": q_clean, "solution_pdf": s_clean,
            "question_crop_pdf": q_crop, "solution_crop_pdf": s_crop,
            "reports": reports}
