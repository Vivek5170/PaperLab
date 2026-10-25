"""PDF / vision tool tests using a dummy PDF with text and shapes."""
from __future__ import annotations

import base64
import io

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from PIL import Image

import database
from tools_extractor import assisted_crop, exact_crop, get_page_image, img_block
from tools_indexer import get_page_text, get_pdf_info, search_pdf_text


def _registered_pid(tmp_db, dummy_pdf, scanned_pdf):
    """Simulate pre-flight so exact_crop's paper_id check passes."""
    return database.register_paper(dummy_pdf, scanned_pdf)


def _tc(tool_name, args, call_id="t1"):
    """Full model ToolCall shape required for InjectedToolCallId tools."""
    return {"name": tool_name, "args": args, "id": call_id, "type": "tool_call"}


def _image_messages(cmd):
    """Split a Command result into (tool text, preview PIL image)."""
    updates = cmd.update["messages"]
    assert len(updates) == 2
    tool_msg, human_msg = updates
    assert isinstance(tool_msg, ToolMessage)
    assert isinstance(human_msg, HumanMessage)
    assert isinstance(tool_msg.content, str)
    text_block, img = human_msg.content
    assert text_block["type"] == "text"
    assert img["type"] == "image_url"
    assert img["image_url"]["url"].startswith("data:image/jpeg;base64,")
    payload = base64.b64decode(img["image_url"]["url"].split(",", 1)[1])
    assert payload[:2] == b"\xff\xd8"  # JPEG preview
    return tool_msg.content, Image.open(io.BytesIO(payload)), payload

def test_get_pdf_info_text_layer(dummy_pdf):
    info = get_pdf_info.invoke({"pdf_path": dummy_pdf})
    assert info["page_count"] == 2
    assert info["has_text_layer"] is True


def test_get_pdf_info_scanned_aborts(scanned_pdf):
    info = get_pdf_info.invoke({"pdf_path": scanned_pdf})
    assert info["page_count"] == 2
    assert info["has_text_layer"] is False


def test_search_pdf_text_case_insensitive(dummy_pdf):
    assert search_pdf_text.invoke({"pdf_path": dummy_pdf, "query": "newton"}) == [1]
    assert search_pdf_text.invoke({"pdf_path": dummy_pdf, "query": "NEWTON"}) == [1]
    assert search_pdf_text.invoke({"pdf_path": dummy_pdf, "query": "solution 1"}) == [2]
    assert search_pdf_text.invoke({"pdf_path": dummy_pdf, "query": "zzz-no-match"}) == []


def test_get_page_text(dummy_pdf):
    text = get_page_text.invoke({"pdf_path": dummy_pdf, "page_number": 1})
    assert "Newton" in text
    try:
        get_page_text.invoke({"pdf_path": dummy_pdf, "page_number": 99})
    except Exception as exc:  # LangChain wraps ValueError; accept either
        assert "99" in str(exc) or "out of range" in str(exc).lower()
    else:
        raise AssertionError("expected out-of-range error")


def test_get_page_image_returns_command_with_preview(dummy_pdf):
    cmd = get_page_image.invoke(_tc(
        "get_page_image", {"pdf_path": dummy_pdf, "page_number": 1},
    ))
    text, preview, _ = _image_messages(cmd)
    assert "Page 1" in text and dummy_pdf in text
    assert preview.size[0] <= 1600 and preview.size[1] <= 1600


def test_img_block_byte_stable(tmp_path):
    from PIL import Image as PILImage

    tiny = tmp_path / "tiny.png"
    PILImage.new("RGB", (200, 200), "white").save(str(tiny))
    a = img_block(str(tiny), 100)
    b = img_block(str(tiny), 100)
    assert a == b  # identical bytes => stable cache prefix
    assert a["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_exact_crop_scaling_and_save(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs):
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    _prime_assist(pid, "fig1.png")
    _prime_assist(pid, "figQ.png")
    out_dir = tmp_outputs / str(pid) / "1"
    # Full-page polygon on the 0-1000 grid must map to full pixel dims.
    cmd = exact_crop.invoke(_tc(
        "exact_crop", {
            "pdf_path": dummy_pdf,
            "page_number": 1,
            "x": 0, "y": 0, "width": 1000, "height": 1000,
            "output_filename": "fig1.png",
            "paper_id": pid,
            "question_number": "1",
        },
    ))
    text, preview, _ = _image_messages(cmd)
    assert "fig1.png" in text
    saved = out_dir / "figures" / "fig1.png"
    assert saved.is_file()

    # Scaling math: disk save is hi-DPI; preview is downscaled as before.
    from tools_extractor import _render_page_to_pil, _SAVE_DPI
    full = _render_page_to_pil(dummy_pdf, 1, _SAVE_DPI)
    cropped = Image.open(saved)
    assert cropped.size == full.size
    assert max(preview.size) <= 600

    # box in a genuinely empty area -> exact dims, no anti-clip growth.
    # (The old (0,0)-(500,500) quarter box sliced the red rect's strokes;
    # the backstop correctly refused to ship that cut.)
    cmd_q = exact_crop.invoke(_tc(
        "exact_crop", {
            "pdf_path": dummy_pdf,
            "page_number": 1,
            "x": 0, "y": 500, "width": 300, "height": 400,
            "output_filename": "figQ.png",
            "paper_id": pid,
            "question_number": "1",
        }, call_id="t2",
    ))
    text_q, preview_q, _ = _image_messages(cmd_q)
    assert "Auto-expanded" not in text_q
    assert max(preview_q.size) <= 600
    q = Image.open(out_dir / "figures" / "figQ.png")
    assert abs(q.size[0] - full.size[0] * 0.3) <= 2
    assert abs(q.size[1] - full.size[1] * 0.4) <= 2


def test_exact_crop_rejects_bad_boxes(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs):
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    bad = [
        {"x": 0, "y": 0, "width": 0, "height": 10},  # zero width
        {"x": 900, "y": 900, "width": 200, "height": 50},  # spills off-grid
        {"x": -5, "y": 0, "width": 10, "height": 10},  # negative corner
    ]
    for i, box in enumerate(bad):
        with pytest.raises(Exception):
            exact_crop.invoke(_tc(
                "exact_crop", {
                    "pdf_path": dummy_pdf,
                    "page_number": 1,
                    **box,
                    "output_filename": "bad.png",
                    "paper_id": pid,
                    "question_number": "1",
                },
                call_id=f"bad{i}",
            ))
    assert not (tmp_outputs / str(pid) / "1" / "figures" / "bad.png").exists()


def test_exact_crop_same_filename_overwrites(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs):
    """Correcting a bad crop reuses the SAME filename and replaces the file."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    _prime_assist(pid, "fig.png")
    out_dir = tmp_outputs / str(pid) / "1"
    first = exact_crop.invoke(_tc(
        "exact_crop", {
            "pdf_path": dummy_pdf,
            "page_number": 1,
            "x": 0, "y": 0, "width": 500, "height": 500,
            "output_filename": "fig.png",
            "paper_id": pid,
            "question_number": "1",
        },
    ))
    _, first_preview, first_bytes = _image_messages(first)
    saved = out_dir / "figures" / "fig.png"
    assert saved.is_file()
    mtime1 = saved.stat().st_mtime_ns
    second = exact_crop.invoke(_tc(
        "exact_crop", {
            "pdf_path": dummy_pdf,
            "page_number": 1,
            "x": 500, "y": 500, "width": 500, "height": 500,
            "output_filename": "fig.png",  # SAME name -> overwrite, no fig_v2
            "paper_id": pid,
            "question_number": "1",
        }, call_id="t2",
    ))
    _, second_preview, second_bytes = _image_messages(second)
    assert saved.is_file()
    assert [p for p in (out_dir / "figures").iterdir()
            if not p.name.startswith("_")] == [saved]
    assert second_bytes != first_bytes  # different region, both saved
    assert saved.stat().st_mtime_ns >= mtime1


def test_exact_crop_lands_in_question_dir(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs):
    """Figures are always saved under Outputs/{paper_id}/{question_number}/."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    _prime_assist(pid, "fig1.png", q="15-17_paragraph")
    cmd = exact_crop.invoke(_tc(
        "exact_crop", {
            "pdf_path": dummy_pdf,
            "page_number": 1,
            "x": 0, "y": 0, "width": 1000, "height": 1000,
            "output_filename": "fig1.png",
            "paper_id": pid,
            "question_number": "15-17_paragraph",
        },
    ))
    _image_messages(cmd)
    saved = tmp_outputs / str(pid) / "15-17_paragraph" / "figures" / "fig1.png"
    assert saved.is_file()


def _pdf_with_images(tmp_path):
    """3-page PDF: per-page diagram (red) on p1, shared logo (blue) on all pages."""
    import fitz

    red = Image.new("RGB", (80, 80), "red")
    buf = io.BytesIO(); red.save(buf, "PNG"); red_raw = buf.getvalue()
    blue = Image.new("RGB", (20, 20), "blue")
    buf2 = io.BytesIO(); blue.save(buf2, "PNG"); blue_raw = buf2.getvalue()
    d = fitz.open()
    for i in range(3):
        p = d.new_page(width=200, height=200)
        p.insert_image(fitz.Rect(150, 10, 170, 30), stream=blue_raw)  # chrome logo
        if i == 0:
            p.insert_image(fitz.Rect(10, 10, 90, 90), stream=red_raw)  # diagram
    pdf = tmp_path / "snap.pdf"
    d.save(str(pdf)); d.close()
    return str(pdf), red_raw, blue_raw


def test_snap_hit_saves_original_bytes(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Case 1 (IoU): tight polygon over an embedded diagram saves original pixels."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, red_raw, _ = _pdf_with_images(tmp_path)
    import tools_extractor as te
    te.reset_assist_attempts()
    te._SNAP_CACHE.clear()
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    cmd = assisted_crop.invoke(_tc("assisted_crop", {
        "pdf_path": pdf, "page_number": 1,
        "x": 50, "y": 50, "width": 400, "height": 400,
        "output_filename": "fig1.png", "paper_id": pid, "question_number": "1",
    }))
    _image_messages(cmd)
    saved = tmp_outputs / str(pid) / "1" / "figures" / "fig1.png"
    got, want = Image.open(saved), Image.open(io.BytesIO(red_raw))
    assert got.size == want.size == (80, 80)
    assert got.convert("RGB").tobytes() == want.convert("RGB").tobytes()


def test_snap_containment_hit(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Case 2 (coverage): generous box holding >=80% of one image snaps it.

    Box (0,0)-(140,140)pt vs 80x80 diagram: IoU ~0.33 (no hit) but the box
    holds 100% of the diagram -> snap. The corner logo stays outside.
    """
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, red_raw, _ = _pdf_with_images(tmp_path)
    import tools_extractor as te
    te.reset_assist_attempts()
    te._SNAP_CACHE.clear()
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    cmd = assisted_crop.invoke(_tc("assisted_crop", {
        "pdf_path": pdf, "page_number": 1,
        "x": 0, "y": 0, "width": 700, "height": 700,
        "output_filename": "figC.png", "paper_id": pid, "question_number": "1",
    }))
    _image_messages(cmd)
    saved = tmp_outputs / str(pid) / "1" / "figures" / "figC.png"
    got, want = Image.open(saved), Image.open(io.BytesIO(red_raw))
    assert got.size == want.size == (80, 80)
    assert got.convert("RGB").tobytes() == want.convert("RGB").tobytes()


def test_snap_ambiguous_box_falls_back(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A box swallowing two whole figures matches neither: plain crop."""
    import fitz

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, _, _ = _pdf_with_images(tmp_path)
    import tools_extractor as te
    te.reset_assist_attempts()
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    # Second non-chrome figure on page 1 so the box holds two whole images.
    green = Image.new("RGB", (40, 40), "green")
    buf = io.BytesIO(); green.save(buf, "PNG")
    d = fitz.open(pdf)
    d[0].insert_image(fitz.Rect(150, 150, 190, 190), stream=buf.getvalue())
    d.save(str(pdf) + ".tmp"); d.close()
    import os as _os
    _os.replace(str(pdf) + ".tmp", pdf)
    cmd = assisted_crop.invoke(_tc("assisted_crop", {
        "pdf_path": pdf, "page_number": 1,
        # whole page: holds the red diagram AND the green square fully
        "x": 0, "y": 0, "width": 1000, "height": 1000,
        "output_filename": "figA.png", "paper_id": pid, "question_number": "1",
    }, call_id="t2"))
    _image_messages(cmd)
    saved = tmp_outputs / str(pid) / "1" / "figures" / "figA.png"
    got = Image.open(saved)
    assert got.size != (80, 80)  # not the snapped red diagram


def test_snap_miss_falls_back_to_plain_crop(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, red_raw, blue_raw = _pdf_with_images(tmp_path)
    import tools_extractor as te
    te.reset_assist_attempts()
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    cmd = assisted_crop.invoke(_tc("assisted_crop", {
        "pdf_path": pdf, "page_number": 1,
        # empty corner: no embedded image here
        "x": 600, "y": 600, "width": 300, "height": 300,
        "output_filename": "figQ.png", "paper_id": pid, "question_number": "1",
    }, call_id="t2"))
    _image_messages(cmd)
    raw = (tmp_outputs / str(pid) / "1" / "figures" / "figQ.png").read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert raw != red_raw and raw != blue_raw


def test_chrome_images_are_not_snapped(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A logo repeated on every page is chrome: snap refuses it."""
    from tools_extractor import _chrome_xrefs

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, _, blue_raw = _pdf_with_images(tmp_path)
    import tools_extractor as te
    te.reset_assist_attempts()
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    assert len(_chrome_xrefs(pdf)) == 1  # the shared logo xref
    cmd = assisted_crop.invoke(_tc("assisted_crop", {
        "pdf_path": pdf, "page_number": 1,
        "x": 750, "y": 50, "width": 100, "height": 100,
        "output_filename": "figL.png", "paper_id": pid, "question_number": "1",
    }))
    _image_messages(cmd)
    raw = (tmp_outputs / str(pid) / "1" / "figures" / "figL.png").read_bytes()
    assert raw != blue_raw  # plain render, not the original chrome bytes


def test_duplicate_xref_reuses_cached_bytes(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Snapping the same xref twice reuses the cached bytes (no re-extract)."""
    import tools_extractor as te
    te.reset_assist_attempts()

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, red_raw, _ = _pdf_with_images(tmp_path)
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    te._SNAP_CACHE.clear()
    pts = (50, 50, 400, 400)
    for name, cid in (("fig1.png", "t1"), ("fig2.png", "t2")):
        assisted_crop.invoke(_tc("assisted_crop", {
            "pdf_path": pdf, "page_number": 1, "x": pts[0], "y": pts[1], "width": pts[2], "height": pts[3],
            "output_filename": name, "paper_id": pid, "question_number": "1",
        }, call_id=cid))
    out = tmp_outputs / str(pid) / "1" / "figures"
    b1, b2 = (out / "fig1.png").read_bytes(), (out / "fig2.png").read_bytes()
    assert b1 == b2  # same xref: second save reuses the cached bytes
    got, want = Image.open(out / "fig1.png"), Image.open(io.BytesIO(red_raw))
    assert got.size == want.size == (80, 80)
    assert got.convert("RGB").tobytes() == want.convert("RGB").tobytes()
    assert len(te._SNAP_CACHE) == 1  # extracted once, reused


def test_snap_huge_box_falls_back(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A huge box holding one small image is NOT a snap (area guard)."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, red_raw, _ = _pdf_with_images(tmp_path)
    import tools_extractor as te
    te.reset_assist_attempts()
    te._SNAP_CACHE.clear()
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    cmd = assisted_crop.invoke(_tc("assisted_crop", {
        "pdf_path": pdf, "page_number": 1,
        # ~whole page: holds 100% of the red diagram but is ~6x its area
        "x": 0, "y": 0, "width": 1000, "height": 950,
        "output_filename": "figH.png", "paper_id": pid, "question_number": "1",
    }, call_id="t9"))
    _image_messages(cmd)
    saved = tmp_outputs / str(pid) / "1" / "figures" / "figH.png"
    got, want = Image.open(saved), Image.open(io.BytesIO(red_raw))
    assert got.size != want.size  # plain render, not the snapped original


def test_exact_crop_unknown_paper_id_fails(dummy_pdf, tmp_db, tmp_outputs):
    with pytest.raises(Exception):
        exact_crop.invoke(_tc(
            "exact_crop", {
                "pdf_path": dummy_pdf,
                "page_number": 1,
                "x": 0, "y": 0, "width": 1000, "height": 1000,
                "output_filename": "fig.png",
                "paper_id": 99999,
                "question_number": "1",
            },
        ))
    assert not (tmp_outputs / "99999").exists()  # no orphan dirs on bad id


def test_exact_crop_rejects_traversal_filename(dummy_pdf, scanned_pdf, tmp_db, tmp_path):
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    with pytest.raises(Exception):
        exact_crop.invoke(_tc(
            "exact_crop", {
                "pdf_path": dummy_pdf,
                "page_number": 1,
                "x": 0, "y": 0, "width": 1000, "height": 1000,
                "output_filename": "../../evil.png",
                "paper_id": pid,
                "question_number": "1",
            },
        ))
    assert not (tmp_path / "evil.png").exists()


# ---------- exact_crop ----------

def _exact(pdf, pid, rect, name, cid="t9", q="1"):
    x, y, w, h = rect
    return exact_crop.invoke(_tc(
        "exact_crop",
        {
            "pdf_path": pdf,
            "page_number": 1,
            "x": x, "y": y, "width": w, "height": h,
            "output_filename": name,
            "paper_id": pid,
            "question_number": q,
        },
        call_id=cid,
    ))


def _prime_assist(pid, name, q="1", n=3):
    import tools_extractor as te

    for _ in range(n):
        te._assist_attempt(pid, q, name)


def test_exact_crop_refused_before_assisted_tries(
        dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Gate: exact box with 0 assisted attempts saves nothing."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, _, _ = _pdf_with_images(tmp_path)
    cmd = _exact(pdf, pid, (0, 0, 500, 500), "e.png")
    updates = cmd.update["messages"]
    assert len(updates) == 1 and "refused" in updates[0].content
    assert "0 of 3" in updates[0].content
    assert not list(tmp_outputs.rglob("e.png"))


def test_exact_crop_ignores_embedded_image(
        dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Polygon is exact-only: even a box around one embedded image renders
    the polygon region, never the original bytes (snap lives in assisted)."""
    import tools_extractor as te

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, red_raw, _ = _pdf_with_images(tmp_path)
    te._SNAP_CACHE.clear()
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    _prime_assist(pid, "e.png")
    # Red diagram is at (10,10)-(90,90) on a 200x200 page: box it loosely.
    cmd = _exact(pdf, pid, (0, 0, 500, 500), "e.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: snap" not in text
    saved = list(tmp_outputs.rglob("e.png"))
    assert saved
    got, want = Image.open(saved[0]), Image.open(io.BytesIO(red_raw))
    assert got.size != (80, 80)  # render of the loose region, not original
    assert te.SNAP_LOG[-1][3] == "exact"


def test_exact_crop_stays_exact_without_image(
        dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """No embedded image under the box: exact render, no snap claim."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)  # strokes only, no embedded images
    _prime_assist(pid, "x.png")
    cmd = _exact(pdf, pid, (300, 300, 200, 350), "x.png")
    text, _, _ = _image_messages(cmd)
    assert "Exact crop of your box" in text and "mode: snap" not in text


# ---------- assisted_crop: vector assist ----------

def _vector_pdf(tmp_path):
    """3-page PDF: figure strokes + labels only on p1, rule on every page."""
    import fitz

    d = fitz.open()
    for i in range(3):
        p = d.new_page(width=600, height=800)
        p.draw_line(fitz.Point(50, 750), fitz.Point(550, 750))  # chrome rule
        if i == 0:
            p.draw_rect(fitz.Rect(200, 300, 400, 500))  # figure
            p.draw_line(fitz.Point(200, 300), fitz.Point(400, 500))
            p.draw_line(fitz.Point(300, 292), fitz.Point(300, 262))  # arrow
            p.insert_text(
                (150, 250),
                "Find the value of the following expression today",
                fontsize=12,
            )
            p.insert_text((205, 292), "E", fontsize=12)  # short label
            p.draw_rect(fitz.Rect(480, 600, 560, 680))  # neighbour, far away
    pdf = tmp_path / "vec.pdf"
    d.save(str(pdf))
    d.close()
    return str(pdf)


def _assist(pdf, pid, rect, name, cid="t1", q="1"):
    import tools_extractor as te

    x, y, w, h = rect
    te.reset_assist_attempts()
    return assisted_crop.invoke(
        _tc(
            "assisted_crop",
            {
                "pdf_path": pdf,
                "page_number": 1,
                "x": x, "y": y, "width": w, "height": h,
                "output_filename": name,
                "paper_id": pid,
                "question_number": q,
            },
            call_id=cid,
        )
    )


def _final_box(text):
    """Parse the reply's rect-form box, return corner ints [x0, y0, x1, y1]."""
    import re

    m = re.search(r"final box: \[([0-9, ]+)\]", text)
    x, y, w, h = (int(v) for v in m.group(1).split(","))
    return [x, y, x + w, y + h]


def test_reply_boxes_are_xywh(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Replies speak (x, y, width, height) -- never corner pairs."""
    import re

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    _prime_assist(pid, "e.png")
    cmd = _exact(pdf, pid, (300, 300, 200, 350), "e.png")
    text, _, _ = _image_messages(cmd)
    m = re.search(r"your box: \[([0-9, ]+)\]\. final box: \[([0-9, ]+)\]", text)
    assert m, text
    your = [int(v) for v in m.group(1).split(",")]
    final = [int(v) for v in m.group(2).split(",")]
    assert your == [300, 300, 200, 350]
    assert final[0] >= 300 - 15 and final[1] >= 300 - 15  # margin, not corners
    assert final[2] >= 200 and final[3] >= 350


def test_assist_completes_clipped_shape(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Box clipping the figure's right half grows to include the whole cluster."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    cmd = _assist(pdf, pid, (300, 300, 200, 350), "a.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text
    assert "extended right by" in text
    assert "(empty margin)" in text  # loose edges shrink to the ink
    box = _final_box(text)
    assert box == [333, 328, 667, 625]  # figure + arrow, nothing else


def test_assist_trims_long_text_keeps_label(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Vector trim fallback: long text line crossing the top edge is
    trimmed on a RAW page (direct _assist_box); short 'E' label stays.

    In production the crop canvas is pre-stripped so this path rarely
    fires -- it remains the safety net when stripping is skipped."""
    import fitz
    import tools_extractor as te

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    _strokes, blocks, clusters = te._page_vectors(pdf, 1)
    doc = fitz.open(pdf)
    try:
        out = te._assist_box(doc[0], fitz.Rect(180, 240, 300, 520),
                             blocks, clusters)
    finally:
        doc.close()
    assert out is not None
    final, trim_notes, _capped, _verdicts = out
    assert any(e == "top" and "Find the value" in (snip or "")
               for e, snip in trim_notes)
    assert 260.0 <= final.y0 <= 266.0  # text gone, stops at arrow stub
    assert (final.x0 <= 205 <= final.x1
            and final.y0 <= 292 <= final.y1)  # 'E' label kept


def test_assist_pre_strips_canvas_before_vector(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Integration: assisted_crop resolves the crop canvas first, so the
    long stem line is already gone when vector matching runs."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    cmd = _assist(pdf, pid, (300, 300, 200, 350), "b.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text
    assert "Find the value" not in text  # stripped before vector saw it
    box = _final_box(text)
    assert box[0] <= 342 <= box[2] and box[1] <= 365 <= box[3]  # 'E' kept


def test_assist_ignores_chrome_stroke(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A box around only the repeated footer rule finds no strokes: plain."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    cmd = _assist(
        pdf, pid,
        (83, 925, 834, 50),  # rule at y=750pt only
        "c.png",
    )
    text, _, _ = _image_messages(cmd)
    assert "mode: plain" in text


def test_assist_idempotent(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Feeding the final box back reproduces the same box and bytes."""
    import tools_extractor as te

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    pts = (300, 300, 200, 350)
    t1, _, _ = _image_messages(_assist(pdf, pid, pts, "d.png"))
    box = _final_box(t1)
    te.reset_assist_attempts()
    t2, _, _ = _image_messages(_assist(
        pdf, pid,
        (box[0], box[1], box[2] - box[0], box[3] - box[1]),
        "d2.png", cid="t2",
    ))
    assert _final_box(t2) == box
    out = tmp_outputs / str(pid) / "1" / "figures"
    assert (out / "d.png").read_bytes() == (out / "d2.png").read_bytes()


def test_assist_sixth_call_refused(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Max 5 assisted calls per figure; the 6th saves nothing."""
    import tools_extractor as te
    from langchain_core.messages import ToolMessage

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    pts = (300, 300, 200, 350)
    te.reset_assist_attempts()
    for i in range(5):
        cmd = assisted_crop.invoke(_tc(
            "assisted_crop",
            {"pdf_path": pdf, "page_number": 1, "x": pts[0], "y": pts[1], "width": pts[2], "height": pts[3],
             "output_filename": "e.png", "paper_id": pid, "question_number": "1"},
            call_id=f"t{i}",
        ))
        assert len(cmd.update["messages"]) == 2  # all 5 allowed through
    dest = tmp_outputs / str(pid) / "1" / "figures" / "e.png"
    before = dest.read_bytes()
    cmd = assisted_crop.invoke(_tc(
        "assisted_crop",
        {"pdf_path": pdf, "page_number": 1, "x": pts[0], "y": pts[1], "width": pts[2], "height": pts[3],
         "output_filename": "e.png", "paper_id": pid, "question_number": "1"},
        call_id="t6",
    ))
    assert len(cmd.update["messages"]) == 1  # text only, no preview
    assert "attempt limit" in cmd.update["messages"][0].content
    assert isinstance(cmd.update["messages"][0], ToolMessage)
    assert dest.read_bytes() == before  # nothing saved


def test_assist_counts_persist_in_sidecar(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Attempts live in figures/_assist_counts.json; reset drops them."""
    import json

    import tools_extractor as te

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    pts = (300, 300, 200, 350)
    te.reset_assist_attempts()
    for i in range(2):
        assisted_crop.invoke(_tc(
            "assisted_crop",
            {"pdf_path": pdf, "page_number": 1, "x": pts[0], "y": pts[1], "width": pts[2], "height": pts[3],
             "output_filename": "f.png", "paper_id": pid, "question_number": "1"},
            call_id=f"c{i}",
        ))
    sidecar = tmp_outputs / str(pid) / "1" / "figures" / "_assist_counts.json"
    assert json.loads(sidecar.read_text()) == {"f.png": 2}
    assert te.reset_assist_attempts(pid) == 1
    assert not sidecar.exists()


def test_exact_crop_is_exact_on_chrome_logo(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Box around the shared logo matches nothing (chrome excluded): exact."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, red_raw, _ = _pdf_with_images(tmp_path)
    import tools_extractor as te

    te._SNAP_CACHE.clear()
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    # 200x200 page: blue logo at (150,10)-(170,30), repeated on all pages.
    _prime_assist(pid, "x.png")
    cmd = exact_crop.invoke(_tc(
        "exact_crop", {
            "pdf_path": pdf, "page_number": 1,
            "x": 700, "y": 0, "width": 200, "height": 200,
            "output_filename": "x.png", "paper_id": pid, "question_number": "1",
        },
    ))
    text, _, _ = _image_messages(cmd)
    assert "Exact crop of your box" in text
    saved = tmp_outputs / str(pid) / "1" / "figures" / "x.png"
    got = Image.open(saved)
    assert (got.size[0], got.size[1]) != (80, 80)  # not the snapped original
    assert te.SNAP_LOG[-1][3] == "exact"


def _line_figure_pdf(tmp_path):
    """Figure drawn as 4 separate lines; bottom edge has a zero-height rect."""
    import fitz

    d = fitz.open()
    p = d.new_page(width=600, height=800)
    p.draw_line(fitz.Point(200, 300), fitz.Point(400, 300))
    p.draw_line(fitz.Point(200, 300), fitz.Point(200, 500))
    p.draw_line(fitz.Point(400, 300), fitz.Point(400, 500))
    p.draw_line(fitz.Point(200, 500), fitz.Point(400, 500))  # ground line
    pdf = tmp_path / "line.pdf"
    d.save(str(pdf))
    d.close()
    return str(pdf)


def test_assist_extends_to_zero_height_line(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A pure horizontal line still extends the box (no silent |= drop)."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _line_figure_pdf(tmp_path)
    cmd = _assist(pdf, pid, (333, 312, 334, 263), "z.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text and "extended bottom by" in text
    assert _final_box(text)[3] == 625  # 500pt ground line


def test_assist_trims_interior_option_line(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Long text fully inside the box, below all strokes, moves the edge up."""
    import fitz

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    d = fitz.open(pdf)
    d[0].insert_text((180, 600), "Option C is correct today", fontsize=12)
    d.save(str(pdf) + ".tmp")
    d.close()
    import os as _os

    _os.replace(str(pdf) + ".tmp", pdf)
    cmd = _assist(pdf, pid, (250, 312, 500, 500), "w.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text and "trimmed bottom by" in text
    box = _final_box(text)
    assert 580 <= box[3] < 812  # text top, not the agent's loose edge
    assert 660 <= box[2] <= 670  # empty right margin shrunk to the ink


def _long_rule_pdf(tmp_path):
    import fitz

    d = fitz.open()
    p = d.new_page(width=600, height=800)
    p.draw_line(fitz.Point(50, 300), fitz.Point(550, 300))  # one-off rule
    pdf = tmp_path / "rule.pdf"
    d.save(str(pdf))
    d.close()
    return str(pdf)


def test_assist_refuses_runaway_growth(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A stroke running far past the box (>3x area) is not applied."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _long_rule_pdf(tmp_path)
    cmd = _assist(pdf, pid, (333, 312, 167, 125), "v.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text and "not applied" in text
    assert _final_box(text) == [333, 312, 500, 437]  # agent's box stands


def test_assist_suppresses_subpixel_noise(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Deltas under 3 units are rounding noise: not reported as corrections."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    # right edge 0.5pt inside the cluster -> 1-unit delta, everything else exact
    cmd = _assist(pdf, pid, (333, 375, 333, 250), "u.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text and "no change needed" in text


def test_assist_trims_short_stray_text_keeps_hugging_label(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """1-word fragment far from strokes is trimmed by _assist_box on a RAW
    page; the close 'E' label stays (canvas pre-strip would also remove
    far debris in aggressive mode)."""
    import fitz
    import tools_extractor as te

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    d = fitz.open(pdf)
    d[0].insert_text((180, 620), "Q12", fontsize=12)
    d.save(str(pdf) + ".tmp")
    d.close()
    import os as _os

    _os.replace(str(pdf) + ".tmp", pdf)
    te._PAGE_VEC_CACHE.clear()
    _strokes, blocks, clusters = te._page_vectors(pdf, 1)
    doc = fitz.open(pdf)
    try:
        out = te._assist_box(doc[0], fitz.Rect(150, 249.6, 450, 649.6),
                             blocks, clusters)
    finally:
        doc.close()
    assert out is not None
    final, trim_notes, _capped, _verdicts = out
    assert any(e == "bottom" and "Q12" in (snip or "")
               for e, snip in trim_notes)
    assert final.y1 < 649.6  # stray fragment pulled the edge up
    assert (final.x0 <= 205 <= final.x1
            and final.y0 <= 292 <= final.y1)  # 'E' kept


def test_assist_idempotent(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Feeding the final box back reproduces the same box and bytes."""
    import tools_extractor as te

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    pts = (300, 300, 200, 350)
    t1, _, _ = _image_messages(_assist(pdf, pid, pts, "d.png"))
    box = _final_box(t1)
    te.reset_assist_attempts()
    t2, _, _ = _image_messages(_assist(
        pdf, pid,
        (box[0], box[1], box[2] - box[0], box[3] - box[1]),
        "d2.png", cid="t2",
    ))
    assert _final_box(t2) == box
    out = tmp_outputs / str(pid) / "1" / "figures"
    assert (out / "d.png").read_bytes() == (out / "d2.png").read_bytes()


def test_assist_sixth_call_refused(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Max 5 assisted calls per figure; the 6th saves nothing."""
    import tools_extractor as te
    from langchain_core.messages import ToolMessage

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    pts = (300, 300, 200, 350)
    te.reset_assist_attempts()
    for i in range(5):
        cmd = assisted_crop.invoke(_tc(
            "assisted_crop",
            {"pdf_path": pdf, "page_number": 1, "x": pts[0], "y": pts[1], "width": pts[2], "height": pts[3],
             "output_filename": "e.png", "paper_id": pid, "question_number": "1"},
            call_id=f"t{i}",
        ))
        assert len(cmd.update["messages"]) == 2  # all 5 allowed through
    dest = tmp_outputs / str(pid) / "1" / "figures" / "e.png"
    before = dest.read_bytes()
    cmd = assisted_crop.invoke(_tc(
        "assisted_crop",
        {"pdf_path": pdf, "page_number": 1, "x": pts[0], "y": pts[1], "width": pts[2], "height": pts[3],
         "output_filename": "e.png", "paper_id": pid, "question_number": "1"},
        call_id="t6",
    ))
    assert len(cmd.update["messages"]) == 1  # text only, no preview
    assert "attempt limit" in cmd.update["messages"][0].content
    assert isinstance(cmd.update["messages"][0], ToolMessage)
    assert dest.read_bytes() == before  # nothing saved


def test_assist_counts_persist_in_sidecar(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Attempts live in figures/_assist_counts.json; reset drops them."""
    import json

    import tools_extractor as te

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    pts = (300, 300, 200, 350)
    te.reset_assist_attempts()
    for i in range(2):
        assisted_crop.invoke(_tc(
            "assisted_crop",
            {"pdf_path": pdf, "page_number": 1, "x": pts[0], "y": pts[1], "width": pts[2], "height": pts[3],
             "output_filename": "f.png", "paper_id": pid, "question_number": "1"},
            call_id=f"c{i}",
        ))
    sidecar = tmp_outputs / str(pid) / "1" / "figures" / "_assist_counts.json"
    assert json.loads(sidecar.read_text()) == {"f.png": 2}
    assert te.reset_assist_attempts(pid) == 1
    assert not sidecar.exists()


def test_exact_crop_is_exact_on_chrome_logo(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Box around the shared logo matches nothing (chrome excluded): exact."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf, red_raw, _ = _pdf_with_images(tmp_path)
    import tools_extractor as te

    te._SNAP_CACHE.clear()
    te._CHROME_CACHE.pop(str(__import__("pathlib").Path(pdf).resolve()), None)
    # 200x200 page: blue logo at (150,10)-(170,30), repeated on all pages.
    _prime_assist(pid, "x.png")
    cmd = exact_crop.invoke(_tc(
        "exact_crop", {
            "pdf_path": pdf, "page_number": 1,
            "x": 700, "y": 0, "width": 200, "height": 200,
            "output_filename": "x.png", "paper_id": pid, "question_number": "1",
        },
    ))
    text, _, _ = _image_messages(cmd)
    assert "Exact crop of your box" in text
    saved = tmp_outputs / str(pid) / "1" / "figures" / "x.png"
    got = Image.open(saved)
    assert (got.size[0], got.size[1]) != (80, 80)  # not the snapped original
    assert te.SNAP_LOG[-1][3] == "exact"


def _line_figure_pdf(tmp_path):
    """Figure drawn as 4 separate lines; bottom edge has a zero-height rect."""
    import fitz

    d = fitz.open()
    p = d.new_page(width=600, height=800)
    p.draw_line(fitz.Point(200, 300), fitz.Point(400, 300))
    p.draw_line(fitz.Point(200, 300), fitz.Point(200, 500))
    p.draw_line(fitz.Point(400, 300), fitz.Point(400, 500))
    p.draw_line(fitz.Point(200, 500), fitz.Point(400, 500))  # ground line
    pdf = tmp_path / "line.pdf"
    d.save(str(pdf))
    d.close()
    return str(pdf)


def test_assist_extends_to_zero_height_line(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A pure horizontal line still extends the box (no silent |= drop)."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _line_figure_pdf(tmp_path)
    cmd = _assist(pdf, pid, (333, 312, 334, 263), "z.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text and "extended bottom by" in text
    assert _final_box(text)[3] == 625  # 500pt ground line


def test_assist_trims_interior_option_line(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Long text fully inside the box, below all strokes, moves the edge up."""
    import fitz

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    d = fitz.open(pdf)
    d[0].insert_text((180, 600), "Option C is correct today", fontsize=12)
    d.save(str(pdf) + ".tmp")
    d.close()
    import os as _os

    _os.replace(str(pdf) + ".tmp", pdf)
    cmd = _assist(pdf, pid, (250, 312, 500, 500), "w.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text and "trimmed bottom by" in text
    box = _final_box(text)
    assert 580 <= box[3] < 812  # text top, not the agent's loose edge
    assert 660 <= box[2] <= 670  # empty right margin shrunk to the ink


def _long_rule_pdf(tmp_path):
    import fitz

    d = fitz.open()
    p = d.new_page(width=600, height=800)
    p.draw_line(fitz.Point(50, 300), fitz.Point(550, 300))  # one-off rule
    pdf = tmp_path / "rule.pdf"
    d.save(str(pdf))
    d.close()
    return str(pdf)


def test_assist_refuses_runaway_growth(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A stroke running far past the box (>3x area) is not applied."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _long_rule_pdf(tmp_path)
    cmd = _assist(pdf, pid, (333, 312, 167, 125), "v.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text and "not applied" in text
    assert _final_box(text) == [333, 312, 500, 437]  # agent's box stands


def test_assist_suppresses_subpixel_noise(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Deltas under 3 units are rounding noise: not reported as corrections."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _vector_pdf(tmp_path)
    # right edge 0.5pt inside the cluster -> 1-unit delta, everything else exact
    cmd = _assist(pdf, pid, (333, 375, 333, 250), "u.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text and "no change needed" in text


def _numbered_header_pdf(tmp_path):
    """Same header position, different numbers per page (running heads)."""
    import fitz

    d = fitz.open()
    for i in range(3):
        p = d.new_page(width=600, height=800)
        p.insert_text((200, 40), "JEE Main Paper %d" % (i + 1), fontsize=12)
        if i == 0:
            p.draw_rect(fitz.Rect(200, 300, 400, 500))
    pdf = tmp_path / "hdr.pdf"
    d.save(str(pdf))
    d.close()
    return str(pdf)


def test_numbered_headers_are_chrome(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Headers differing only by number match across pages: ignored."""
    import tools_extractor as te

    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _numbered_header_pdf(tmp_path)
    te._CHROME_TEXT.clear()
    te._PAGE_VEC_CACHE.clear()
    cs, ct = te._chrome_for(pdf)
    assert len(ct) == 1  # digit-normalized header matched on all 3 pages
    # A box around header text only finds no strokes and no text: plain.
    cmd = _assist(pdf, pid, (300, 20, 400, 60), "h.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: plain" in text


def test_vector_render_has_ink_margin(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """Exact-bounds box: reported box unchanged, render gains margin."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _line_figure_pdf(tmp_path)
    cmd = _assist(
        pdf, pid,
        (333, 375, 334, 250),  # exact figure bounds
        "p.png",
    )
    text, _, _ = _image_messages(cmd)
    assert _final_box(text) == [333, 375, 667, 625]
    assert "Auto-expanded" in text  # grazed edges grew the render
    saved = Image.open(tmp_outputs / str(pid) / "1" / "figures" / "p.png")
    w, h = saved.size
    px = saved.convert("L").load()
    assert min(px[x, y] for x in range(w) for y in (0, 1, h - 2, h - 1)) > 200
    assert min(px[x, y] for y in range(h) for x in (0, 1, w - 2, w - 1)) > 200


def _grazed_text_pdf(tmp_path):
    """Text block grazed by a stroke tip that stops above the cut line."""
    import fitz

    d = fitz.open()
    p = d.new_page(width=600, height=800)
    p.draw_rect(fitz.Rect(200, 300, 400, 500))
    p.draw_line(fitz.Point(300, 262), fitz.Point(300, 259))  # stub ends in text zone
    p.insert_text((150, 250), "Find the value of the following expression today", fontsize=12)
    pdf = tmp_path / "graze.pdf"
    d.save(str(pdf))
    d.close()
    return str(pdf)


def test_grazing_stroke_does_not_veto_trim(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A stroke ending inside the text zone must not save the text line."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _grazed_text_pdf(tmp_path)
    cmd = _assist(pdf, pid, (250, 250, 500, 500), "g.png")
    text, _, _ = _image_messages(cmd)
    assert "mode: vector" in text and "trimmed top by" in text


def _label_in_strip_pdf(tmp_path):
    """Kept label straddles the option block's cut line; wire stays clear."""
    import fitz

    d = fitz.open()
    p = d.new_page(width=600, height=800)
    p.draw_rect(fitz.Rect(200, 300, 400, 500))
    p.draw_line(fitz.Point(400, 400), fitz.Point(438, 400))  # stops short
    p.insert_text((432, 408), "V0", fontsize=12)  # hugs wire, straddles x=440
    p.insert_text((440, 313), "Option D is correct today", fontsize=12)
    pdf = tmp_path / "strip.pdf"
    d.save(str(pdf))
    d.close()
    return str(pdf)


def test_trim_never_slices_kept_label(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs, tmp_path):
    """A side trim vetoed when its strip holds a kept label (no ink there)."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    pdf = _label_in_strip_pdf(tmp_path)
    cmd = _assist(pdf, pid, (250, 312, 500, 500), "k.png")
    text, _, _ = _image_messages(cmd)
    box = _final_box(text)
    assert box == [333, 375, 744, 625]  # right edge stops at the label, not 440
    assert "(text line" not in text  # the option-tail trim never fired
