"""PDF cleaning tests: chrome/ground/pattern removal + fail-open plumbing.

Synthetic dirty PDFs are built with fitz (shared xrefs forced via
``xref=`` reuse, the way real chrome works). The real-watermark case runs
against the repo's AITS PDF when present, skipped otherwise (data/ is
gitignored, so CI clones lack it).
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pytest

import database
import directory_manager
from pdf_clean import clean_paper_pdfs, clean_pdf_canvas

ARCHIVE_AITS = (
    Path(__file__).parent.parent / "data" / "archive"
    / "AITS-2324-PT-II-JEEA-Paper-2.pdf"
)


def _text_doc(tmp_path, name="dirty.pdf", pages=3, with_text=True):
    """Multi-page PDF with a live text layer on every page."""
    p = tmp_path / name
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=612, height=792)
        if with_text:
            page.insert_text(
                (72, 100 + i * 5),
                f"Question {i + 1}: the value is {i * 7} with E = mc2. "
                "Padding words to clear the fifty character guard easily.",
            )
    doc.save(str(p))
    doc.close()
    return str(p)


def _resave(doc, pdf_path):
    """Save back over the opened file (save-to-self needs a temp hop)."""
    tmp = str(pdf_path) + ".tmp.pdf"
    doc.save(tmp, garbage=4)
    doc.close()
    Path(tmp).replace(pdf_path)


def _shared_image(pdf_path, pages=(0, 1, 2)):
    """Stamp one image xref onto several pages; return the xref."""
    doc = fitz.open(pdf_path)
    px = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40))
    px.clear_with(100)
    first = doc[pages[0]]
    first.insert_image(fitz.Rect(450, 700, 550, 760), pixmap=px)
    xref = first.get_images(full=True)[-1][0]
    for pi in pages[1:]:
        doc[pi].insert_image(fitz.Rect(450, 700, 550, 760), xref=xref)
    _resave(doc, pdf_path)
    return xref


def _page_digests(page):
    import hashlib
    out = []
    for img in page.get_images(full=True):
        try:
            px = fitz.Pixmap(page.parent, img[0])
            out.append((hashlib.md5(px.samples).hexdigest(), px.width))
        except Exception:
            pass
    return out


def test_chrome_images_deleted_text_kept(tmp_path):
    src = _text_doc(tmp_path)
    d = fitz.open(src)
    before = [d[i].get_text() for i in range(3)]
    d.close()
    _shared_image(src)
    src_doc = fitz.open(src)
    gray = [d for pg in src_doc for d in _page_digests(pg) if d[1] == 40]
    assert len(gray) == 3  # the 40px gray stamp on all 3 pages
    src_doc.close()
    out = str(tmp_path / "clean.pdf")
    rep = clean_pdf_canvas(src, out, min_pages=3)
    assert rep["chrome_images"] == 3
    doc = fitz.open(out)
    try:
        for i in range(3):
            assert not [d for d in _page_digests(doc[i]) if d[1] == 40]
            assert doc[i].get_text() == before[i]
    finally:
        doc.close()


def test_chrome_below_threshold_kept(tmp_path):
    src = _text_doc(tmp_path)
    _shared_image(src, pages=(0, 1))  # only 2 of 3 pages
    out = str(tmp_path / "clean.pdf")
    rep = clean_pdf_canvas(src, out, min_pages=3)
    assert rep["chrome_images"] == 0


def test_background_whitened_text_kept(tmp_path):
    src = _text_doc(tmp_path, pages=2)
    doc = fitz.open(src)
    px = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 200, 200))
    px.clear_with(180)
    pages = list(doc)
    pages[0].insert_image(pages[0].rect, pixmap=px, overlay=False)
    xref = pages[0].get_images(full=True)[-1][0]
    pages[1].insert_image(pages[1].rect, xref=xref, overlay=False)
    t0 = [pg.get_text() for pg in pages]
    _resave(doc, src)
    out = str(tmp_path / "clean.pdf")
    rep = clean_pdf_canvas(src, out, bg_min_pages=2)
    assert rep["backgrounds"] == 1
    doc = fitz.open(out)
    try:
        assert [pg.get_text() for pg in doc] == t0
        corner = doc[0].get_pixmap(dpi=50).samples[0:3]
        assert tuple(corner) == (255, 255, 255)
    finally:
        doc.close()


def test_background_single_page_kept_by_default(tmp_path):
    """A one-off full-page image is a figure until proven repeating."""
    src = _text_doc(tmp_path, pages=1)
    doc = fitz.open(src)
    px = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 200, 200))
    px.clear_with(180)
    doc[0].insert_image(doc[0].rect, pixmap=px, overlay=False)
    _resave(doc, src)
    out = str(tmp_path / "clean.pdf")
    rep = clean_pdf_canvas(src, out)  # production defaults
    assert rep["backgrounds"] == 0


@pytest.mark.skipif(not ARCHIVE_AITS.is_file(), reason="needs local archive PDF")
def test_gray_patterns_whitened_real_pdf(tmp_path):
    out = str(tmp_path / "clean.pdf")
    rep = clean_pdf_canvas(str(ARCHIVE_AITS), out)
    assert rep["patterns"] == 86  # ~7 tiling watermarks x 13 pages
    d0, d1 = fitz.open(str(ARCHIVE_AITS)), fitz.open(out)
    try:
        assert sum(len(p.get_text()) for p in d1) == sum(
            len(p.get_text()) for p in d0)
    finally:
        d0.close()
        d1.close()


def test_clean_paper_pdfs_caches_and_keeps_db_originals(
        tmp_db, tmp_path, monkeypatch, dummy_pdf):
    s = tmp_path / "s.pdf"
    s.write_bytes(Path(dummy_pdf).read_bytes())
    pid = database.register_paper(dummy_pdf, str(s))
    monkeypatch.setattr(directory_manager, "CLEANED_DIR", tmp_path / "cleaned")
    first = clean_paper_pdfs(pid)
    assert Path(first["question_pdf"]).is_file()
    assert first["question_pdf"] != dummy_pdf  # cleaned copy, not original
    row = database.get_paper(pid)
    assert row["question_pdf_path"] == dummy_pdf  # DB untouched
    second = clean_paper_pdfs(pid)
    assert second["question_pdf"] == first["question_pdf"]  # reused
    assert second["reports"]["question"] == {"reused": True}


def test_clean_paper_pdfs_fail_open(tmp_db, tmp_path, monkeypatch):
    q = tmp_path / "q.pdf"
    q.write_bytes(b"not a pdf at all")
    pid = database.register_paper(str(q))
    monkeypatch.setattr(directory_manager, "CLEANED_DIR", tmp_path / "cleaned")
    out = clean_paper_pdfs(pid)  # must not raise
    assert out["question_pdf"] == str(q)
    assert out["solution_pdf"] is None


def test_clean_paper_pdfs_unknown_paper(tmp_db):
    with pytest.raises(ValueError):
        clean_paper_pdfs(99999)


# --------------------------------------------- anti-clip expansion (exact paths)


def _filled_rect_pdf(tmp_path, name="clip.pdf"):
    """Black filled rect at exact unit coords: x 600-900, y 300-700."""
    import fitz

    p = tmp_path / name
    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.draw_rect(fitz.Rect(367.2, 237.6, 550.8, 554.4), fill=(0, 0, 0))
    doc.save(str(p))
    doc.close()
    return str(p)


def _tool_text(cmd):
    return cmd.update["messages"][0].content


def _prime(pid, q, name, n=3):
    from tools_extractor import _assist_attempt
    for _ in range(n):
        _assist_attempt(pid, q, name)


def test_expand_box_clears_slight_clip(tmp_path):
    from tools_extractor import (_EDGE_CHECK_DPI, _expand_box_for_ink,
                                 _touching_ink)
    import fitz

    doc = fitz.open(_filled_rect_pdf(tmp_path))
    try:
        page = doc[0]
        grown, pads, capped, blocked = _expand_box_for_ink(
            page, [601.0, 300.0, 900.0, 700.0])
        assert pads[0] > 0  # 1 unit inside the filled edge
        assert capped == [] and blocked == []  # slight clip fully cleared
        assert grown[0] < 600.0  # pushed back past the true edge
        r = page.rect
        clip = fitz.Rect(grown[0] / 1000 * r.width, grown[1] / 1000 * r.height,
                        grown[2] / 1000 * r.width, grown[3] / 1000 * r.height)
        assert _touching_ink(
            page.get_pixmap(dpi=_EDGE_CHECK_DPI, clip=clip)) == [False] * 4
    finally:
        doc.close()


def test_expand_box_caps_on_wire(tmp_path):
    """An edge that can never clear (full-height line) stops at the cap."""
    import fitz
    from tools_extractor import _expand_box_for_ink

    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.draw_line(fitz.Point(306, 0), fitz.Point(306, 792), color=(0, 0, 0),
                 width=2)
    try:
        grown, pads, capped, blocked = _expand_box_for_ink(
            pg, [490.0, 200.0, 510.0, 800.0])
        assert pads[1] == pads[3] == 15.0  # top/bottom capped
        assert pads[0] == pads[2] == 0.0  # sides never touched ink
        assert grown[1] < 200.0 and grown[3] > 800.0
        assert sorted(capped) == ["bottom", "top"]  # still touching: retry me
    finally:
        doc.close()


def test_polygon_autoexpands_and_reports(tmp_db, tmp_outputs, tmp_path,
                                        dummy_pdf):
    from tools_extractor import polygon_crop

    pid = database.register_paper(dummy_pdf)
    pdf = _filled_rect_pdf(tmp_path)
    _prime(pid, "1", "qfig1.png")
    cmd = polygon_crop.invoke({
        "name": "polygon_crop",
        "args": {"pdf_path": pdf, "page_number": 1,
                 "points": [(601, 300), (900, 300), (900, 700), (601, 700)],
                 "output_filename": "qfig1.png", "paper_id": pid,
                 "question_number": "1"},
        "id": "t1", "type": "tool_call",
    })
    text = _tool_text(cmd)
    assert "Auto-expanded" in text and "left" in text
    import fitz
    saved = tmp_outputs / str(pid) / "1" / "figures" / "qfig1.png"
    img = fitz.Pixmap(str(saved))
    try:
        # filled rect fully inside WITH margin: first dark column is not
        # the border column (a 1px AA fringe at most)
        w, h = img.width, img.height
        s, n = img.samples, img.n
        dark_col = next(
            (x for x in range(w)
             if min(s[(y * w + x) * n] for y in range(0, h, 3)) < 128),
            w)
        assert dark_col >= 2, f"content cut at the edge (col {dark_col})"
    finally:
        img = None


def test_expansion_stops_at_question_text(tmp_path):
    """An edge on question text does not grow into it; it reports blocked."""
    import fitz
    from tools_extractor import _expand_box_for_ink

    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.insert_text((72, 400),
                   "This is a deliberately long question stem with many words",
                   fontsize=12)
    pg.draw_rect(fitz.Rect(420, 238, 550, 396), fill=(0, 0, 0))
    try:
        # left edge (550u) sits on the stem text; right edge (899u)
        # sits exactly on the filled rect; top/bottom far from everything.
        grown, pads, capped, blocked = _expand_box_for_ink(
            pg, [550.0, 200.0, 899.0, 700.0])
        assert blocked == ["left"]  # grew nowhere into the stem
        assert pads[0] == 0.0
        assert pads[2] > 0  # diagram side still expands normally
        assert capped == []
    finally:
        doc.close()


def test_polygon_reports_still_cut_at_cap(tmp_db, tmp_outputs, tmp_path,
                                          dummy_pdf):
    """Box deep inside content: pads max out and the reply says retry."""
    from tools_extractor import polygon_crop

    pid = database.register_paper(dummy_pdf)
    pdf = _filled_rect_pdf(tmp_path)
    _prime(pid, "1", "qfig1.png")
    cmd = polygon_crop.invoke({
        "name": "polygon_crop",
        "args": {"pdf_path": pdf, "page_number": 1,
                 "points": [(700, 400), (800, 400), (800, 600), (700, 600)],
                 "output_filename": "qfig1.png", "paper_id": pid,
                 "question_number": "1"},
        "id": "t1", "type": "tool_call",
    })
    text = _tool_text(cmd)
    assert "Still cut" in text and "move that edge outward" in text


def test_generous_box_gets_no_expansion_note(tmp_db, tmp_outputs, tmp_path,
                                            dummy_pdf):
    from tools_extractor import polygon_crop

    pid = database.register_paper(dummy_pdf)
    pdf = _filled_rect_pdf(tmp_path)
    _prime(pid, "1", "qfig1.png")
    cmd = polygon_crop.invoke({
        "name": "polygon_crop",
        "args": {"pdf_path": pdf, "page_number": 1,
                 "points": [(580, 280), (920, 280), (920, 720), (580, 720)],
                 "output_filename": "qfig1.png", "paper_id": pid,
                 "question_number": "1"},
        "id": "t1", "type": "tool_call",
    })
    assert "Auto-expanded" not in _tool_text(cmd)
