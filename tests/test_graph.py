"""Graph tests: deterministic nodes and routing (no LLM calls)."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import database
import graph
from graph import (
    abort_node,
    extractor_init_node,
    route_extractor,
    route_extractor_init,
    route_indexer,
    text_layer_gate,
)


def _paper_with_bounds(tmp_db, tmp_path, tag="g"):
    q = tmp_path / f"{tag}_q.pdf"
    s = tmp_path / f"{tag}_s.pdf"
    q.write_bytes(b"Q")
    s.write_bytes(b"S")
    pid = database.register_paper(str(q), str(s))
    conn = database.get_connection()
    try:
        conn.execute(
            "UPDATE papers SET paper_name='P', q_start=7, q_end=13, "
            "s_start=10, s_end=12 WHERE id = ?",
            (pid,),
        )
        conn.commit()
    finally:
        conn.close()
    return pid, str(q), str(s)


def test_text_layer_gate(tmp_db):
    assert text_layer_gate({"q_has_text": False}) == "abort"
    assert text_layer_gate({"q_has_text": True}) == "indexer"


def test_abort_node_archives_and_sets_status(tmp_db, tmp_path):
    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")
    pid = database.register_paper(str(q))
    out = abort_node({"paper_id": pid})
    assert out == {"status": "aborted_no_text"}
    assert database.get_paper(pid)["archive"] == 1


def test_extractor_init_populates_from_db(tmp_db, tmp_path):
    pid, q, s = _paper_with_bounds(tmp_db, tmp_path)
    out = extractor_init_node({"paper_id": pid})
    assert out["q_start"] == 7 and out["q_end"] == 13
    assert out["s_start"] == 10 and out["s_end"] == 12
    assert out["question_pdf_path"] == q and out["solution_pdf_path"] == s


def test_extractor_init_respects_clean_paths(tmp_db, tmp_path):
    pid, q, s = _paper_with_bounds(tmp_db, tmp_path)
    out = extractor_init_node({
        "paper_id": pid,
        "question_pdf_path": "/clean/q.pdf",
        "solution_pdf_path": "/clean/s.pdf",
    })
    # Clean paths are left untouched (absent from the update); only
    # boundaries are filled in.
    assert "question_pdf_path" not in out and "solution_pdf_path" not in out
    assert out["q_start"] == 7 and out["s_end"] == 12


def test_extractor_init_aborted_paper(tmp_db, tmp_path):
    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")
    pid = database.register_paper(str(q))
    database.mark_paper_archived(pid)  # never indexed -> NULL boundaries
    assert extractor_init_node({"paper_id": pid}) == {"status": "aborted_no_text"}


def test_extractor_init_unknown_paper_fails(tmp_db):
    with pytest.raises(ValueError):
        extractor_init_node({"paper_id": 99999})


def _seed_questions(pid, names):
    import database

    conn = database.get_connection()
    try:
        conn.executemany(
            "INSERT INTO questions (paper_id, question_number) VALUES (?, ?)",
            [(pid, n) for n in names],
        )
        conn.commit()
    finally:
        conn.close()


def test_existing_id_scheme(tmp_db, tmp_path):
    from graph import _existing_id_scheme

    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")
    pid = database.register_paper(str(q))
    assert _existing_id_scheme(pid) is None  # fresh paper: model decides once
    _seed_questions(pid, ["1", "2", "15-17_paragraph"])
    assert _existing_id_scheme(pid) == "bare"
    q2 = tmp_path / "q2.pdf"
    q2.write_bytes(b"Q2")
    pid2 = database.register_paper(str(q2))
    _seed_questions(pid2, ["A-01", "B-31-32_paragraph"])
    assert _existing_id_scheme(pid2) == "namespaced"


def test_route_extractor_init(tmp_db):
    assert route_extractor_init({"status": "aborted_no_text"}) == "end"
    assert route_extractor_init({"paper_id": 1}) == "extractor"  # partial state ok


def test_route_extractor(tmp_db):
    ai_tools = AIMessage(content="", tool_calls=[
        {"name": "get_page_image", "args": {}, "id": "1", "type": "tool_call"},
    ])
    assert route_extractor({"messages": [ai_tools]}) == "continue"
    assert route_extractor({"messages": [AIMessage(content="done")]}) == "done"
    assert route_extractor({"messages": []}) == "continue"


def test_route_indexer_submit_and_idle(tmp_db):
    ai_submit = AIMessage(content="", tool_calls=[
        {"name": "submit_metadata_and_boundaries", "args": {}, "id": "1", "type": "tool_call"},
    ])
    assert route_indexer({"messages": [ai_submit]}) == "done"
    assert route_indexer({"messages": [AIMessage(content="waiting")]}) == "done"
    assert route_indexer({"messages": [HumanMessage(content="hi")]}) == "continue"


def test_graphs_compile(tmp_db):
    assert graph.phase1_app is not None
    assert graph.extractor_app is not None
    assert graph.app is not None
