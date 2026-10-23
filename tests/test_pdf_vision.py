"""PDF / vision tool tests using a dummy PDF with text and shapes."""
from __future__ import annotations

import base64

import pytest

import database
from tools_extractor import get_page_image, polygon_crop
from tools_indexer import get_page_text, get_pdf_info, search_pdf_text


def _registered_pid(tmp_db, dummy_pdf, scanned_pdf):
    """Simulate pre-flight so polygon_crop's paper_id check passes."""
    return database.register_paper(dummy_pdf, scanned_pdf)

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


def test_get_page_image_returns_png_b64(dummy_pdf):
    b64 = get_page_image.invoke({"pdf_path": dummy_pdf, "page_number": 1})
    raw = base64.b64decode(b64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_polygon_crop_scaling_and_save(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs):
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    out_dir = tmp_outputs / str(pid) / "1"
    # Full-page polygon on the 0-1000 grid must map to full pixel dims.
    b64 = polygon_crop.invoke({
        "pdf_path": dummy_pdf,
        "page_number": 1,
        "points": [(0, 0), (1000, 0), (1000, 1000), (0, 1000)],
        "output_filename": "fig1.png",
        "paper_id": pid,
        "question_number": "1",
    })
    saved = out_dir / "figures" / "fig1.png"
    assert saved.is_file()
    assert base64.b64decode(b64)[:8] == b"\x89PNG\r\n\x1a\n"

    # Scaling math: rendered page size must match cropped dims for full grid.
    from PIL import Image
    import io
    full = Image.open(io.BytesIO(base64.b64decode(
        get_page_image.invoke({"pdf_path": dummy_pdf, "page_number": 1})
    )))
    cropped = Image.open(saved)
    assert cropped.size == full.size

    # Quarter-page polygon -> roughly quarter dims (bbox crop).
    b64q = polygon_crop.invoke({
        "pdf_path": dummy_pdf,
        "page_number": 1,
        "points": [(0, 0), (500, 0), (500, 500), (0, 500)],
        "output_filename": "figQ.png",
        "paper_id": pid,
        "question_number": "1",
    })
    assert base64.b64decode(b64q)[:8] == b"\x89PNG\r\n\x1a\n"
    q = Image.open(out_dir / "figures" / "figQ.png")
    assert abs(q.size[0] - full.size[0] // 2) <= 2
    assert abs(q.size[1] - full.size[1] // 2) <= 2


def test_polygon_crop_rejects_bad_points(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs):
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    with pytest.raises(Exception):
        polygon_crop.invoke({
            "pdf_path": dummy_pdf,
            "page_number": 1,
            "points": [(0, 0), (10, 10)],  # fewer than 3 points
            "output_filename": "bad.png",
            "paper_id": pid,
            "question_number": "1",
        })
    assert not (tmp_outputs / str(pid) / "1" / "figures" / "bad.png").exists()


def test_polygon_crop_same_filename_overwrites(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs):
    """Correcting a bad crop reuses the SAME filename and replaces the file."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    out_dir = tmp_outputs / str(pid) / "1"
    first = polygon_crop.invoke({
        "pdf_path": dummy_pdf,
        "page_number": 1,
        "points": [(0, 0), (500, 0), (500, 500), (0, 500)],
        "output_filename": "fig.png",
        "paper_id": pid,
        "question_number": "1",
    })
    saved = out_dir / "figures" / "fig.png"
    assert saved.is_file()
    mtime1 = saved.stat().st_mtime_ns
    second = polygon_crop.invoke({
        "pdf_path": dummy_pdf,
        "page_number": 1,
        "points": [(500, 500), (1000, 500), (1000, 1000), (500, 1000)],
        "output_filename": "fig.png",  # SAME name -> overwrite, no fig_v2
        "paper_id": pid,
        "question_number": "1",
    })
    assert saved.is_file()
    assert list((out_dir / "figures").iterdir()) == [saved]
    assert second != first  # different region -> different bytes
    assert saved.stat().st_mtime_ns >= mtime1


def test_polygon_crop_lands_in_question_dir(dummy_pdf, scanned_pdf, tmp_db, tmp_outputs):
    """Figures are always saved under Outputs/{paper_id}/{question_number}/."""
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    b64 = polygon_crop.invoke({
        "pdf_path": dummy_pdf,
        "page_number": 1,
        "points": [(0, 0), (1000, 0), (1000, 1000), (0, 1000)],
        "output_filename": "fig1.png",
        "paper_id": pid,
        "question_number": "15-17_paragraph",
    })
    assert base64.b64decode(b64)[:8] == b"\x89PNG\r\n\x1a\n"
    saved = tmp_outputs / str(pid) / "15-17_paragraph" / "figures" / "fig1.png"
    assert saved.is_file()


def test_polygon_crop_unknown_paper_id_fails(dummy_pdf, tmp_db, tmp_outputs):
    with pytest.raises(Exception):
        polygon_crop.invoke({
            "pdf_path": dummy_pdf,
            "page_number": 1,
            "points": [(0, 0), (1000, 0), (1000, 1000), (0, 1000)],
            "output_filename": "fig.png",
            "paper_id": 99999,
            "question_number": "1",
        })
    assert not (tmp_outputs / "99999").exists()  # no orphan dirs on bad id


def test_polygon_crop_rejects_traversal_filename(dummy_pdf, scanned_pdf, tmp_db, tmp_path):
    pid = _registered_pid(tmp_db, dummy_pdf, scanned_pdf)
    with pytest.raises(Exception):
        polygon_crop.invoke({
            "pdf_path": dummy_pdf,
            "page_number": 1,
            "points": [(0, 0), (1000, 0), (1000, 1000), (0, 1000)],
            "output_filename": "../../evil.png",
            "paper_id": pid,
            "question_number": "1",
        })
    assert not (tmp_path / "evil.png").exists()
