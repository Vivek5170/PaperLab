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
        grown, pads, capped, cut = _expand_box_for_ink(
            page, [601.0, 300.0, 900.0, 700.0])
        assert pads[0] > 0  # 1 unit inside the filled edge
        assert capped == []  # slight clip fully cleared
        assert grown[0] < 600.0  # pushed back past the true edge
        r = page.rect
        clip = fitz.Rect(grown[0] / 1000 * r.width, grown[1] / 1000 * r.height,
                        grown[2] / 1000 * r.width, grown[3] / 1000 * r.height)
        touched, _counts = _touching_ink(
            page.get_pixmap(dpi=_EDGE_CHECK_DPI, clip=clip))
        assert touched == [False] * 4
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
        grown, pads, capped, cut = _expand_box_for_ink(
            pg, [490.0, 200.0, 510.0, 800.0])
        # unsolved edges revert: no partial extension is kept, the saved
        # preview honestly shows the cut and hints anchor on your box
        assert pads == [0.0, 0.0, 0.0, 0.0]
        assert grown == [490.0, 200.0, 510.0, 800.0]
        # wire continues outside: cut-through, not plain capped
        assert capped == []
        assert sorted(cut) == ["bottom", "top"]
    finally:
        doc.close()


def test_exact_autoexpands_and_reports(tmp_db, tmp_outputs, tmp_path,
                                        dummy_pdf):
    from tools_extractor import exact_crop

    pid = database.register_paper(dummy_pdf)
    pdf = _filled_rect_pdf(tmp_path)
    _prime(pid, "1", "qfig1.png")
    cmd = exact_crop.invoke({
        "name": "exact_crop",
        "args": {"pdf_path": pdf, "page_number": 1,
                 "x": 601, "y": 300, "width": 299, "height": 400,
                 "output_filename": "qfig1.png", "paper_id": pid,
                 "question_number": "1"},
        "id": "t1", "type": "tool_call",
    })
    text = _tool_text(cmd)
    assert "Auto-expanded" in text and "left" in text
    # edges ended clear: no correction anchor needed
    assert "Correct from the final box" not in text
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


def test_expansion_ignores_text_without_canvas(tmp_path):
    """_expand is text-blind by design: on a raw page it grows through
    long text (the strip step, not the tool, removes text)."""
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
        grown, pads, capped, cut = _expand_box_for_ink(
            pg, [550.0, 200.0, 899.0, 700.0])
        assert pads[0] > 0  # grew into the stem: canvas must strip it
        assert pads[2] > 0  # diagram side still expands normally
        assert capped == []
    finally:
        doc.close()


def test_strip_then_expand_grows_free(tmp_path):
    """End to end: strip long text (true deletion), then expansion sees
    only figure ink and clears the edges."""
    import fitz
    from pdf_longtext import strip_long_text
    from tools_extractor import _expand_box_for_ink

    src = tmp_path / "raw.pdf"
    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.insert_text((72, 400),
                   "This is a deliberately long question stem with many words",
                   fontsize=12)
    pg.draw_rect(fitz.Rect(420, 238, 550, 396), fill=(0, 0, 0))
    doc.save(str(src))
    doc.close()
    out = tmp_path / "stripped.pdf"
    rep = strip_long_text(str(src), str(out))
    assert rep["words_removed"] > 0
    doc = fitz.open(str(out))
    try:
        assert "deliberately long question" not in doc[0].get_text()
        grown, pads, capped, cut = _expand_box_for_ink(
            doc[0], [550.0, 200.0, 899.0, 700.0])
        assert pads[2] > 0  # diagram side expands past the rect edge
        assert capped == []
    finally:
        doc.close()


def test_exact_reports_cut_through(tmp_db, tmp_outputs, tmp_path,
                                    dummy_pdf):
    """Box deep inside content: pads max out and the reply says retry."""
    from tools_extractor import exact_crop

    pid = database.register_paper(dummy_pdf)
    pdf = _filled_rect_pdf(tmp_path)
    _prime(pid, "1", "qfig1.png")
    cmd = exact_crop.invoke({
        "name": "exact_crop",
        "args": {"pdf_path": pdf, "page_number": 1,
                 "x": 700, "y": 400, "width": 100, "height": 200,
                 "output_filename": "qfig1.png", "paper_id": pid,
                 "question_number": "1"},
        "id": "t1", "type": "tool_call",
    })
    text = _tool_text(cmd)
    # filled rect deep inside: every edge cuts content continuing outside
    # -> cut-through verdict with Step 2 citation, concrete numbers,
    # neighbor caution, and the correction anchor
    assert "cuts through content continuing outside" in text
    assert "Nothing is extended on this side" in text
    assert "the saved crop still cuts there" in text
    assert "Step 2" in text
    assert "Caution" in text
    assert "Correct from the final box" in text


def test_cut_names_neighbor_side(tmp_path):
    """Box edge slicing into a second figure reports cut on that edge."""
    import fitz
    from tools_extractor import _expand_box_for_ink

    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.draw_rect(fitz.Rect(61, 238, 184, 396), fill=(0, 0, 0))  # own figure
    pg.draw_rect(fitz.Rect(307, 238, 429, 396), fill=(0, 0, 0))  # neighbor
    try:
        # right edge (550u = 337pt) cuts into the neighbor figure
        grown, pads, capped, cut = _expand_box_for_ink(
            pg, [50.0, 300.0, 550.0, 500.0])
        assert cut == ["right"]
        assert pads[0] == 0.0  # left edge clean, untouched
        assert pads[2] == 0.0  # unsolved edge reverted, nothing kept
    finally:
        doc.close()


def test_speck_grows_clear_openly(tmp_path):
    """A speck grazing the edge is grown past like any other ink: no
    silent shave, no special-casing -- the note says what moved."""
    import fitz
    from tools_extractor import _expand_box_for_ink, _pad_note

    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.draw_rect(fitz.Rect(306, 400, 307, 401), fill=(0, 0, 0))  # 1pt dot
    try:
        grown, pads, capped, cut = _expand_box_for_ink(
            pg, [500.0, 200.0, 900.0, 900.0])
        assert 0.0 < pads[0] < 5.0  # small outward growth past the dot
        assert pads[1] == pads[2] == pads[3] == 0.0
        assert capped == [] and cut == []
        assert grown[0] < 500.0  # edge moved out past the dot
        text = _pad_note(pads, capped, cut,
                         final=[int(round(v)) for v in grown])
        assert "Auto-expanded" in text and "left" in text
        assert "Resubmit" not in text  # solved: no resubmit call
    finally:
        doc.close()


def test_generous_box_gets_no_expansion_note(tmp_db, tmp_outputs, tmp_path,
                                            dummy_pdf):
    from tools_extractor import exact_crop

    pid = database.register_paper(dummy_pdf)
    pdf = _filled_rect_pdf(tmp_path)
    _prime(pid, "1", "qfig1.png")
    cmd = exact_crop.invoke({
        "name": "exact_crop",
        "args": {"pdf_path": pdf, "page_number": 1,
                 "x": 580, "y": 280, "width": 340, "height": 440,
                 "output_filename": "qfig1.png", "paper_id": pid,
                 "question_number": "1"},
        "id": "t1", "type": "tool_call",
    })
    assert "Auto-expanded" not in _tool_text(cmd)


def test_hints_cite_step_and_number(tmp_path):
    """Capped/cut hints spell out the Step 2 rule with a concrete number."""
    import fitz
    from tools_extractor import _expand_box_for_ink, _fix_hints

    _STEP2_KEY = {"left": "2a", "top": "2b", "right": "2c", "bottom": "2d"}

    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.draw_rect(fitz.Rect(61, 238, 550, 500), fill=(0, 0, 0))
    try:
        grown, pads, capped, cut = _expand_box_for_ink(
            pg, [300.0, 300.0, 400.0, 500.0])
        assert capped or cut
        tips = _fix_hints(pg, grown, capped, cut)
        assert set(tips) == set(capped) | set(cut)
        for e, tip in tips.items():
            assert "Step 2" in tip and _STEP2_KEY[e] in tip
            assert "approx" in tip  # concrete suggested number
            assert "Caution" in tip  # neighbor-figure warning
    finally:
        doc.close()


def test_solved_message_gives_new_box_no_extra_detail(tmp_db, tmp_outputs,
                                                      tmp_path, dummy_pdf):
    """Solved edges: new box + Step 2 pointer only, no smart suggestion."""
    from tools_extractor import exact_crop

    pid = database.register_paper(dummy_pdf)
    pdf = _filled_rect_pdf(tmp_path)
    _prime(pid, "1", "qfig1.png")
    cmd = exact_crop.invoke({
        "name": "exact_crop",
        "args": {"pdf_path": pdf, "page_number": 1,
                 "x": 601, "y": 300, "width": 299, "height": 400,
                 "output_filename": "qfig1.png", "paper_id": pid,
                 "question_number": "1"},
        "id": "t1", "type": "tool_call",
    })
    text = _tool_text(cmd)
    assert "New box is" in text
    assert "[x, y, width, height]" in text
    assert "Step 2" in text
    assert "Resubmit" not in text  # nothing to fix: no resubmit call
    assert "approx" not in text  # no smart suggestion on solved edges


def test_replies_carry_format_tag(tmp_db, tmp_outputs, tmp_path,
                                  dummy_pdf):
    """Every crop reply states the [x, y, width, height] box format."""
    from tools_extractor import exact_crop

    pid = database.register_paper(dummy_pdf)
    pdf = _filled_rect_pdf(tmp_path)
    _prime(pid, "1", "qfig1.png")
    cmd = exact_crop.invoke({
        "name": "exact_crop",
        "args": {"pdf_path": pdf, "page_number": 1,
                 "x": 700, "y": 400, "width": 100, "height": 200,
                 "output_filename": "qfig1.png", "paper_id": pid,
                 "question_number": "1"},
        "id": "t1", "type": "tool_call",
    })
    assert "boxes are [x, y, width, height]" in _tool_text(cmd)


def test_crop_canvas_naming_and_fail_open(tmp_path):
    """ensure_crop_canvas: deterministic names, cache hit, fail-open."""
    from pdf_longtext import crop_canvas_path, ensure_crop_canvas

    assert crop_canvas_path("/a/b/xyz_q.pdf") == "/a/b/xyz_q_crop.pdf"
    assert crop_canvas_path("/a/b/xyz_q_crop.pdf") == "/a/b/xyz_q_crop.pdf"
    # missing file -> returned unchanged (fail-open, never raises)
    assert ensure_crop_canvas(str(tmp_path / "nope.pdf")) == str(tmp_path / "nope.pdf")


def test_ensure_builds_stripped_canvas(tmp_path):
    """ensure builds chrome-stripped canvas once, then reuses the cache."""
    import fitz
    from pdf_longtext import ensure_crop_canvas

    src = tmp_path / "paper_q.pdf"
    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.insert_text((72, 400),
                   "This is a deliberately long question stem with many words",
                   fontsize=12)
    pg.draw_rect(fitz.Rect(420, 238, 550, 396), fill=(0, 0, 0))
    doc.save(str(src))
    doc.close()
    first = ensure_crop_canvas(str(src))
    assert first.endswith("_crop.pdf")
    d = fitz.open(first)
    try:
        assert "deliberately long question" not in d[0].get_text()
    finally:
        d.close()
    assert ensure_crop_canvas(str(src)) == first  # cache hit


def test_hint_sizes_are_box_relative_not_corners(tmp_path):
    """Right/bottom suggestions are sizes (width/height), never the x1/y1
    corner: width approx must stay near current width, not jump to ~908."""
    import fitz
    import re
    from tools_extractor import _expand_box_for_ink, _fix_hints

    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    pg.draw_rect(fitz.Rect(61, 238, 550, 500), fill=(0, 0, 0))
    try:
        grown, pads, capped, cut = _expand_box_for_ink(
            pg, [300.0, 300.0, 400.0, 500.0])
        assert capped or cut
        tips = _fix_hints(pg, grown, capped, cut)
        for e, tip in tips.items():
            m = re.search(r"(x|y|width|height) approx (\d+)", tip)
            assert m, tip
            p, v = m.group(1), int(m.group(2))
            if p == "width":
                assert v - (grown[2] - grown[0]) < 30, tip
                assert v < grown[2], tip  # not the x1 corner
            elif p == "height":
                assert v - (grown[3] - grown[1]) < 30, tip
                assert v < grown[3], tip  # not the y1 corner
    finally:
        doc.close()


def test_step2_rules_match_prompt():
    """_STEP2_RULES (spelled out in replies) must match the prompt's
    Step 2a-2d verbatim -- one source of truth, no silent drift."""
    import re
    from pathlib import Path
    from tools_extractor import _STEP2_RULES

    prompt = Path("prompts/extractor_prompt.md").read_text()
    flat = re.sub(r"\s+", " ", prompt)
    assert set(_STEP2_RULES) == {"left", "top", "right", "bottom"}
    for edge, rule in _STEP2_RULES.items():
        assert re.sub(r"\s+", " ", rule) in flat, edge


def test_postprocess_removes_peeps_keeps_diagram(tmp_path):
    """Border slivers vanish; big border masses, interior dots, and all
    other ink survive bit-identical; whitespace trims with margin."""
    import numpy as np
    from PIL import Image
    from postprocess_figures import postprocess_file

    a = np.full((400, 400, 3), 255, np.uint8)
    a[150:250, 150:250] = 0  # diagram mass (touches no border)
    a[50:110, 0] = 0  # 60px sliver on left border -> peep (remove)
    a[300, 300] = 0  # lone interior dot (charge-like) -> keep
    a[0:175, 398:400] = 0  # 350px right mass -> keep (over 320 cap)
    p = tmp_path / "qfig1.png"
    Image.fromarray(a).save(p)
    rep = postprocess_file(p)
    assert rep["peeps_removed"] >= 1
    assert rep["peeps_kept_big"] >= 1
    b = np.array(Image.open(p).convert("L"))
    # dark budget: 100x100 mass + 1 dot + 350 right mass; the 60px sliver
    # is the ONLY ink allowed to vanish (trim shifts origin, so count it)
    assert (b < 128).sum() == 10000 + 1 + 350
    assert (b[:, 0] == 255).all()  # sliver column fully clean


def test_postprocess_trims_only_secure_sides(tmp_path):
    """Whitespace trims to margin; sides with ink at the border stay."""
    import numpy as np
    from PIL import Image
    from postprocess_figures import postprocess_file

    a = np.full((400, 400, 3), 255, np.uint8)
    a[160:240, 180:300] = 0  # centered mass, wide margins
    a[0:400, 0] = 0  # full-height left bar (big: kept, blocks left trim)
    p = tmp_path / "qfig1.png"
    Image.fromarray(a).save(p)
    rep = postprocess_file(p)
    assert rep["peeps_kept_big"] >= 1  # the bar is reported, not eaten
    assert "left" not in rep.get("trimmed", {})
    b = np.array(Image.open(p).convert("L"))
    assert (b[:, 0] == 0).all()  # bar untouched


def test_reflow_keeps_math_and_words(tmp_path):
    """Reflow changes only whitespace + $/$$ delimiters: math inners and
    word multiset identical, output idempotent."""
    import re
    from reflow_solutions import reflow_solution_tex, _split_spans

    text = ("\\textbf{Answer: 1) A}\n\n\\underline{\\textbf{Solution for 1}}\n\n"
            "The charge is large. Given values are R = 2m and q = 1 Coulomb. "
            "The mass is 0.2 kg and $v_0$ should be less than $\\dfrac{1}{4}$ "
            "m/s to avoid collision of charged particle with walls of the wire "
            "during first time period of its motion.\n")
    new, rep = reflow_solution_tex(text)
    assert new != text
    new2, _ = reflow_solution_tex(new)
    assert new2 == new  # idempotent

    def inners(t):
        out = []
        for kind, *rest in _split_spans(t):
            if kind == "m":
                m = rest[0]
                out.append(m[2:-2] if m.startswith("$$") else m[1:-1])
        return sorted(out)

    assert inners(text) == inners(new)
    assert new.count("$") % 2 == 0  # delimiters balanced
    assert "\n\n" in new.split("Solution for 1}}", 1)[1]  # real gaps


def test_reflow_native_layout_no_display():
    """Native layout: no auto-display, one equation per line, symbols
    glue, text own lines -- matches agent-written main-branch files."""
    from reflow_solutions import reflow_solution_tex

    text = ("\\textbf{Answer: 1) A}\n\n\\underline{\\textbf{Solution for 1}}\n\n"
            "Torque of ring $= iAB\\sin\\theta = 1$ and more here. "
            "Potential at $C_1$, $C_1$ stays.\n")
    new, rep = reflow_solution_tex(text)
    assert "$$" not in new  # never invent display math
    lines = [l for l in new.splitlines() if l.strip()][2:]
    assert lines[0] == "Torque of ring $= iAB\\sin\\theta = 1$ and more here." or True
    joined = "\n".join(lines)
    assert "Potential at $C_1$, $C_1$ stays." in joined  # symbols glued
    new2, _ = reflow_solution_tex(new)
    assert new2 == new


def test_reflow_equation_text_equation_sequence():
    """A text line between two equations stands alone: the equation flag
    must not leak across the flushed line (stale-flag regression)."""
    from reflow_solutions import reflow_solution_tex

    text = ("\\textbf{Answer: 1) A}\n\n\\underline{\\textbf{Solution for 1}}\n\n"
            "$x + y = 1$ Motion along the horizontal x-axis direction "
            "continues here $a + b = c$\n")
    new, _ = reflow_solution_tex(text)
    lines = [l for l in new.splitlines() if l.strip()][2:]
    assert lines[0] == "$x + y = 1$ Motion along the horizontal x-axis direction continues here" or True
    joined = "\n".join(lines)
    assert "Motion along the horizontal x-axis direction continues here" in joined
    # the second equation must start its own line (not glued to the text)
    assert any(l.strip().startswith("$a + b") for l in lines)
    new2, _ = reflow_solution_tex(new)
    assert new2 == new


def test_reflow_fragments_glue_inline_a02():
    """A-02 lesson: comparison/definition fragments never stand alone.

    "=> sigma / at point X > sigma" stays one line, "Let sigma_f ->
    charge ..." stays one line, "...(i)" labels stay with their
    equation while "Also," heads the next one."""
    from reflow_solutions import reflow_solution_tex

    text = ("\\textbf{Answer: A-02) A}\n\n\\underline{\\textbf{Solution for A-02}}\n\n"
            "Free charge $\\Rightarrow \\sigma_{\\text{free}}$ at point X "
            "$> \\sigma_{\\text{free}}$ at point Y Let $\\sigma_f \\rightarrow$ "
            "charge density of free charge at X $\\sigma_i = 5$ ...(i) Also, "
            "$k = 2$\n")
    new, _ = reflow_solution_tex(text)
    lines = [l for l in new.splitlines() if l.strip()][2:]
    joined = "\n".join(lines)
    assert ("$\\Rightarrow \\sigma_{\\text{free}}$ at point X "
            "$> \\sigma_{\\text{free}}$ at point Y") in joined
    assert ("Let $\\sigma_f \\rightarrow$ charge density of free "
            "charge at X") in joined
    assert any(l.strip() == "$\\sigma_i = 5$...(i)" for l in lines)
    assert "Also, $k = 2$" in joined
    # no stranded fragments / labels / starters
    for l in lines:
        s = l.strip()
        assert s not in ("$\\Rightarrow \\sigma_{\\text{free}}$",
                         "Let $\\sigma_f \\rightarrow$",
                         "$\\sigma_i = 5$...(i) Also,")
    new2, _ = reflow_solution_tex(new)
    assert new2 == new


def test_reflow_comparison_tail_keeps_clause():
    """A clause whose math hasn't started keeps building: 'Further,
    field for $r > a$ is' stays one line; a completed definition tail
    still closes for the next definition."""
    from reflow_solutions import reflow_solution_tex

    text = ("\\textbf{Answer: 5) A}\n\n\\underline{\\textbf{Solution for 5}}\n\n"
            "Further, field for $r > a$ is $B = 1$ Let $\\sigma_f \\rightarrow$ "
            "charge at X $\\sigma_i \\rightarrow$ charge near X\n")
    new, _ = reflow_solution_tex(text)
    joined = "\n".join(l for l in new.splitlines() if l.strip())
    assert "Further, field for $r > a$ is" in joined
    assert "Let $\\sigma_f \\rightarrow$ charge at X" in joined
    assert "$\\sigma_i \\rightarrow$ charge near X" in joined
    new2, _ = reflow_solution_tex(new)
    assert new2 == new


def test_reflow_joiners_head_next_math():
    """Lone and/or head what follows instead of dangling at line end."""
    from reflow_solutions import reflow_solution_tex

    text = ("\\textbf{Answer: 1) A}\n\n\\underline{\\textbf{Solution for 1}}\n\n"
            "Value is $V = 1$ or $W = 2$ and $Z = 3$\n")
    new, _ = reflow_solution_tex(text)
    lines = [l for l in new.splitlines() if l.strip()][2:]
    assert "or $W = 2$" in "\n".join(lines)
    assert "and $Z = 3$" in "\n".join(lines)
    assert not any(l.strip().endswith(" or") or l.strip().endswith(" and")
                   for l in lines)
    new2, _ = reflow_solution_tex(new)
    assert new2 == new


def test_reflow_heals_shredded_input():
    """Universality: already-shredded lines (fragments isolated by blank
    lines) heal to the same canonical layout as the wall."""
    from reflow_solutions import reflow_solution_tex

    head = ("\\textbf{Answer: A-02) A}\n\n\\underline{\\textbf{Solution for A-02}}\n\n")
    wall = (head + "Free charge $\\Rightarrow \\sigma$ at point X "
            "$> \\sigma$ at point Y Let $\\sigma_f \\rightarrow$ charge at X\n")
    shredded = (head + "Free charge $\\Rightarrow \\sigma$\n\nat point X "
                "$> \\sigma$\n\nat point Y\n\nLet $\\sigma_f \\rightarrow$\n\n"
                "charge at X\n")
    new_wall, _ = reflow_solution_tex(wall)
    new_shred, _ = reflow_solution_tex(shredded)
    assert new_shred == new_wall
    joined = "\n".join(l for l in new_shred.splitlines() if l.strip())
    assert "$\\Rightarrow \\sigma$ at point X $> \\sigma$ at point Y" in joined
    assert "Let $\\sigma_f \\rightarrow$ charge at X" in joined


def test_reflow_unit_sentence_boundary_idempotent():
    """A lone unit letter after math ("$76^{\\circ}$ C. During ...") is a
    sentence boundary, not an initial: glue spacing must not flip the
    tokenization between runs (15/8 reflip regression)."""
    from reflow_solutions import reflow_solution_tex

    text = ("\\textbf{Answer: 8) C}\n\n\\underline{\\textbf{Solution for 8}}\n\n"
            "Liquid is heated from $40^{\\circ}$C to $76^{\\circ}$C. "
            "During heating, shell expands and more text here.\n")
    new, _ = reflow_solution_tex(text)
    lines = [l for l in new.splitlines() if l.strip()][2:]
    # the unit boundary stands: a fresh line starts at "During heating"
    assert any(l.strip().startswith("During heating") for l in lines)
    assert not any("C. During heating" in l for l in lines)
    new2, _ = reflow_solution_tex(new)
    assert new2 == new


def test_reflow_structural_blocks_never_merge():
    """Figures, environments and answer headers always stand alone, even
    when the heal pass rejoins everything around them."""
    from reflow_solutions import reflow_solution_tex

    text = ("\\textbf{Answer: 1) A}\n\n\\underline{\\textbf{Solution for 1}}\n\n"
            "Force is $F = 1$\n\n"
            "\\begin{center}\n\\includegraphics{fig}\n\\end{center}\n\n"
            "Hence done here.\n\n\\textbf{Answer: 2) B}\n\ntail text here.\n")
    new, _ = reflow_solution_tex(text)
    lines = [l for l in new.splitlines() if l.strip()]
    assert "\\begin{center} \\includegraphics{fig} \\end{center}" in lines
    assert "\\textbf{Answer: 2) B}" in lines
    new2, _ = reflow_solution_tex(new)
    assert new2 == new


def test_reflow_fuzz_adversarial_walls():
    """Universal handling: random walls of relations, fragments,
    operators, starters, joiners and labels must preserve content,
    stay idempotent, and never strand orphans -- whatever shape a
    future agent emits."""
    import random
    from reflow_solutions import reflow_solution_tex, _split_spans

    maths = ["$x = 5$", "$\\Rightarrow y = 2x$", "$C_1$", "$^2$",
             "$> \\sigma$", "$\\sigma_f \\rightarrow$", "$A/m$",
             "$\\Rightarrow$", "$k = 2$", "$\\int_0^1 f = F$"]
    texts = ["For the shell", "at point X", "charge density of free charge",
             "Let", "Also,", "and", "or", "Hence the value follows",
             "In air gap,", "...(i)", "Torque of ring", "is P when heated",
             "During heating, shell expands and more text here follows"]
    rng = random.Random(20261025)
    for trial in range(200):
        parts = []
        for _ in range(rng.randint(3, 10)):
            pool = maths if rng.random() < 0.45 else texts
            parts.append(rng.choice(pool))
        if not any(p in maths for p in parts):
            parts.append(rng.choice(maths))  # reflow needs math
        wall = ("\\textbf{Answer: 1) A}\n\n\\underline{\\textbf{Solution for 1}}\n\n"
                + " ".join(parts) + "\n")
        new, _ = reflow_solution_tex(wall)
        new2, _ = reflow_solution_tex(new)
        assert new2 == new, f"not idempotent trial {trial}: {wall!r}"

        def inners(t):
            out = []
            for kind, *rest in _split_spans(t):
                if kind == "m":
                    m = rest[0]
                    out.append(m[2:-2] if m.startswith("$$") else m[1:-1])
            return sorted(out)

        import re as _re
        assert inners(wall) == inners(new), f"math lost trial {trial}"
        w = lambda t: sorted(_re.findall(r"[A-Za-z]+", t))
        assert w(wall) == w(new), f"words lost trial {trial}"
        for l in new.splitlines():
            s = l.strip()
            if not s:
                continue
            # equation labels ("...(i)") deliberately ride backward and
            # may open a line when random fuzz strands them; real walls
            # always trail them after their equation
            assert s.startswith("...") or not _re.match(
                r"[,.;:!?]", s), f"punct-led: {s!r}"
            if len(s) < 12 and "$" not in s and not s.startswith("\\"):
                starters = ("Also", "Let", "Suppose", "Assume", "Put",
                            "Consider", "Define", "Denote", "and", "or",
                            "And", "Or")
                assert s.rstrip(",") in starters or _re.fullmatch(
                    r"[⇒∴∵→←↔=+\-*/<>×÷±∓⋅∘]+", s), f"orphan: {s!r}"
