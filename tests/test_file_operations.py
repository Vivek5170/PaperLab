"""File-operation tests: exact Outputs/{paper_id}/{question_number}/ hierarchy."""
from __future__ import annotations

import directory_manager as dm


def test_ensure_question_dir_creates_hierarchy(tmp_outputs):
    qdir = dm.ensure_question_dir(3, "15a", tmp_outputs)
    assert qdir == tmp_outputs / "3" / "15a"
    assert qdir.is_dir()
    assert (qdir / "figures").is_dir()


def test_grouped_question_number_folder_verbatim(tmp_outputs):
    qdir = dm.ensure_question_dir(7, "15-17_paragraph", tmp_outputs)
    assert (tmp_outputs / "7" / "15-17_paragraph").is_dir()
    assert (qdir / "figures").is_dir()


def test_get_question_dir_no_side_effects(tmp_outputs):
    p = dm.get_question_dir(1, "2", tmp_outputs)
    assert str(p).endswith("Outputs/1/2".replace("/", __import__("os").sep))
    assert not p.exists()


def test_solution_placeholder_created_once(tmp_outputs):
    qdir = dm.ensure_question_dir(1, "1", tmp_outputs)
    sol = dm.ensure_solution_placeholder(qdir)
    assert sol.read_text(encoding="utf-8") == dm.SOLUTION_PLACEHOLDER
    # Second call must not overwrite a real solution.
    sol.write_text("real", encoding="utf-8")
    assert dm.ensure_solution_placeholder(qdir).read_text(encoding="utf-8") == "real"


def test_idempotent_dir_creation(tmp_outputs):
    a = dm.ensure_question_dir(5, "1", tmp_outputs)
    b = dm.ensure_question_dir(5, "1", tmp_outputs)
    assert a == b and a.is_dir()


def test_rejects_traversal_question_number(tmp_outputs):
    import pytest

    for bad in ("../evil", "/absolute", "..", "a/b", ""):
        with pytest.raises(ValueError):
            dm.ensure_question_dir(1, bad, tmp_outputs)
    # Nothing escaped the Outputs base, and nothing was created inside it.
    assert not tmp_outputs.exists() or list(tmp_outputs.iterdir()) == []
