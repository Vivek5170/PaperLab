"""Shared pytest fixtures: isolated SQLite DB, isolated Outputs dir, dummy PDF."""
from __future__ import annotations

import sys
from pathlib import Path

import fitz  # PyMuPDF
import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database
import directory_manager


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point database.DB_PATH at a temp file and initialise schema."""
    db_path = tmp_path / "test_physics_archive.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setenv("PHYSICS_ARCHIVE_DB", str(db_path))
    database.init_db()
    return db_path


@pytest.fixture()
def tmp_outputs(tmp_path, monkeypatch):
    """Point the Outputs base at a temp dir."""
    out = tmp_path / "Outputs"
    monkeypatch.setattr(directory_manager, "OUTPUT_BASE", out)
    monkeypatch.setenv("PHYSICS_OUTPUT_BASE", str(out))
    return out


@pytest.fixture()
def dummy_pdf(tmp_path):
    """Two-page PDF: page 1 has question text + a rectangle; page 2 solutions."""
    pdf_path = tmp_path / "dummy.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 100), "Question 1: What is Newton's second law?")
    p1.insert_text((72, 130), "F = ma is the answer.")
    p1.draw_rect(fitz.Rect(100, 200, 300, 350), color=(1, 0, 0), width=2)
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 100), "Solution 1: F equals m times a.")
    p2.insert_text((72, 130), "Detailed derivation of F = ma.")
    doc.save(str(pdf_path))
    doc.close()
    return str(pdf_path)


@pytest.fixture()
def scanned_pdf(tmp_path):
    """Image-only PDF with no text layer (blank pages)."""
    pdf_path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page(width=595, height=842)
        # Vector shape only -- get_text() stays empty.
        page.draw_circle(fitz.Point(300, 400), 100, color=(0, 0, 1), width=3)
    doc.save(str(pdf_path))
    doc.close()
    return str(pdf_path)
