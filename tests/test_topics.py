"""Node 3 (run_topics) tests: output parsing + fill-only protection (no LLM)."""
from __future__ import annotations

import pytest

import run_topics


def test_parse_full_reply():
    out = run_topics.parse_topics_output(
        "TOPICS: 42, 117\nDIFFICULTY: Medium\nSUGGESTION: NONE", 296)
    assert out == {"numbers": [42, 117], "difficulty": "Medium",
                   "suggestion": None, "errors": []}


def test_parse_none_topics_needs_suggestion():
    out = run_topics.parse_topics_output(
        "TOPICS: NONE\nDIFFICULTY: Hard\nSUGGESTION: mixes rotation and SHM", 296)
    assert out["numbers"] == [] and out["difficulty"] == "Hard"
    assert out["suggestion"] == "mixes rotation and SHM"
    assert out["errors"] == []


def test_parse_degrades_each_field():
    out = run_topics.parse_topics_output(
        "TOPICS: 7, 999, abc\nDIFFICULTY: Extreme\nSUGGESTION: new topic?", 296)
    assert out["numbers"] == [7]  # valid one kept
    assert out["difficulty"] is None
    assert out["suggestion"] == "new topic?"
    assert len(out["errors"]) == 3  # out-of-range, bad word, bad difficulty


def test_parse_missing_lines():
    out = run_topics.parse_topics_output("hello", 296)
    assert out == {"numbers": [], "difficulty": None, "suggestion": None,
                   "errors": ["missing TOPICS line", "missing DIFFICULTY line",
                              "missing SUGGESTION line",
                              "no topics and no suggestion: nothing to store"]}


def test_topic_list_stable_and_numbered(tmp_db):
    import database as _db

    _db.init_topics()
    lines = run_topics.build_topic_list()
    assert len(lines) == 296
    assert [n for n, _ in lines] == list(range(1, 297))
    assert "Vectors" in lines[0][1]  # tree order, paths carry context
    assert any("Friction" in p for _, p in lines)


def test_topic_crud_guards(tmp_db):
    import database as _db

    _db.init_topics()
    code = _db.add_topic("PH05-W1", "subtopic", "Test topic", "for tests")
    assert code == "PH05.08"
    node = _db.get_topic(code)
    assert node["rev"] == 1
    assert _db.update_topic(code, "Test topic 2", "d", 1) == 2
    with pytest.raises(ValueError):  # stale rev
        _db.update_topic(code, "X", "d", 1)
    with pytest.raises(ValueError):  # cross-chapter move
        _db.move_topic(code, "PH06-W1")
    assert _db.move_topic(code, "PH05-W2") is True
    assert _db.get_topic(code)["parent"] == "PH05-W2"
    with pytest.raises(ValueError):  # bad level placement
        _db.add_topic("PH05", "subtopic", "Nope", "")
    assert _db.delete_topic(code) is True
    with pytest.raises(ValueError):  # children block delete
        _db.delete_topic("PH05")


def test_add_module_generates_next_code(tmp_db):
    import database as _db

    _db.init_topics()
    assert _db.add_module("Test Module") == "M6"
    assert _db.get_topic("M6")["level"] == "module"
    assert _db.add_topic("M6", "chapter", "Test Chapter", "") == "PH42"
    with pytest.raises(ValueError):
        _db.add_module("  ")


def test_only_fill_never_overwrites_human_grade(tmp_db, tmp_path):
    import database as _db

    q = tmp_path / "q.pdf"
    q.write_bytes(b"qq")
    pid = _db.register_paper(str(q))
    conn = _db.get_connection()
    try:
        conn.execute(
            "INSERT INTO questions (paper_id, question_number) VALUES (?, '1')",
            (pid,))
        conn.commit()
    finally:
        conn.close()
    # Human grades first.
    assert _db.set_question_difficulty(pid, "1", "Hard") is True
    # Auto parse says Medium: human grade must survive.
    assert _db.set_question_difficulty(pid, "1", "Medium", only_fill=True) is True
    conn = _db.get_connection()
    try:
        assert conn.execute(
            "SELECT difficulty FROM questions WHERE paper_id = ?",
            (pid,)).fetchone()["difficulty"] == "Hard"
    finally:
        conn.close()
    # Auto fills a blank column.
    assert _db.set_question_difficulty(pid, "1", None) is True  # clear
    assert _db.set_question_difficulty(pid, "1", "Easy", only_fill=True) is True
    conn = _db.get_connection()
    try:
        assert conn.execute(
            "SELECT difficulty FROM questions WHERE paper_id = ?",
            (pid,)).fetchone()["difficulty"] == "Easy"
    finally:
        conn.close()
