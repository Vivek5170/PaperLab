"""Pipeline tests: status flow (mocked apps), token math, migration."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

import database
import run_pipeline as rp_mod
from run_pipeline import _wipe_paper, run_pipeline, summarize_tokens


def _reg(tmp_db, tmp_path, tag="pl"):
    q = tmp_path / f"{tag}_q.pdf"
    s = tmp_path / f"{tag}_s.pdf"
    q.write_bytes(b"Q")
    s.write_bytes(b"S")
    return database.register_paper(str(q), str(s))


class FakeApp:
    def __init__(self, final, called=None, name=""):
        self._final = final
        self.called = [] if called is None else called
        self._name = name

    def invoke(self, state, config=None):
        self.called.append(self._name)
        if self._name == "indexer" and self._final.get("status") == "indexer_complete":
            # Mirror a real submit: boundaries land in the DB row.
            conn = database.get_connection()
            try:
                conn.execute(
                    "UPDATE papers SET q_start=1, q_end=2, s_start=3, s_end=4,"
                    " sol_section_start=1 WHERE id=?", (state["paper_id"],))
                conn.commit()
            finally:
                conn.close()
        return dict(self._final)


def _mock_apps(monkeypatch, idx_status="indexer_complete", ext_status="extractor_complete"):
    idx_calls, ext_calls = [], []
    monkeypatch.setattr(
        rp_mod, "phase1_app",
        FakeApp({"status": idx_status, "messages": []}, idx_calls, "indexer"),
    )
    monkeypatch.setattr(
        rp_mod, "extractor_app",
        FakeApp({"status": ext_status, "messages": []}, ext_calls, "extractor"),
    )
    return idx_calls, ext_calls


def test_run_pipeline_happy_path(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    pid = _reg(tmp_db, tmp_path)
    idx_calls, ext_calls = _mock_apps(monkeypatch)
    out = run_pipeline(pid)
    assert out["status"] == "done"
    assert idx_calls == ["indexer"] and ext_calls == ["extractor"]
    assert database.get_paper(pid)["status"] == "done"
    assert out["summary"]["total"]["turns"] == 0  # mocked apps log nothing


def test_run_pipeline_split_failed_skips_extractor(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    pid = _reg(tmp_db, tmp_path)
    idx_calls, ext_calls = _mock_apps(monkeypatch, idx_status="split_failed")
    out = run_pipeline(pid)
    assert out["status"] == "failed"
    assert ext_calls == []
    assert database.get_paper(pid)["status"] == "failed"


def test_run_pipeline_idle_indexer_never_goes_done(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    """LLM stops without submitting: failed, extractor never runs."""
    pid = _reg(tmp_db, tmp_path)
    idx_calls, ext_calls = _mock_apps(monkeypatch, idx_status="running")
    out = run_pipeline(pid)
    assert out["status"] == "failed"
    assert ext_calls == []
    assert database.get_paper(pid)["status"] == "failed"


def test_run_pipeline_aborted_skips_extractor(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    pid = _reg(tmp_db, tmp_path)
    idx_calls, ext_calls = _mock_apps(monkeypatch, idx_status="aborted_no_text")
    out = run_pipeline(pid)
    assert out["status"] == "failed"
    assert ext_calls == []  # extractor never ran
    row = database.get_paper(pid)
    assert row["status"] == "failed" and "text layer" in (row["error"] or "")


def test_run_pipeline_refuses_done_without_force(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    pid = _reg(tmp_db, tmp_path)
    _mock_apps(monkeypatch)
    database.set_paper_status(pid, "done")
    with pytest.raises(ValueError, match="already done"):
        run_pipeline(pid)


def test_run_pipeline_force_wipes_and_reruns(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    pid = _reg(tmp_db, tmp_path)
    _mock_apps(monkeypatch)
    # Stale artifacts from a previous run.
    qdir = tmp_outputs / str(pid) / "1"
    (qdir / "figures").mkdir(parents=True)
    (qdir / "question.tex").write_text("old")
    database.log_token_usage(pid, "indexer", input_tokens=10)
    conn = database.get_connection()
    try:
        conn.execute(
            "INSERT INTO questions (paper_id, question_number) VALUES (?, '1')", (pid,)
        )
        conn.commit()
    finally:
        conn.close()
    out = run_pipeline(pid, force=True)
    assert out["status"] == "done"
    assert not (tmp_outputs / str(pid)).exists()
    assert database.get_paper(pid)["status"] == "done"
    assert summarize_tokens(pid)["total"]["turns"] == 0  # old rows wiped


def test_run_pipeline_force_resets_combined_split(
        tmp_db, tmp_path, tmp_outputs, monkeypatch):
    """Force rerun on a split combined paper: split removed, same-file
    solution restored, stale boundaries cleared before re-index."""
    pid = _reg(tmp_db, tmp_path)
    split = tmp_path / f"{pid:02d}_x_solsplit.pdf"
    split.write_bytes(b"SPLIT")
    conn = database.get_connection()
    try:
        conn.execute(
            "UPDATE papers SET paper_name='Old', q_start=1, q_end=6, "
            "s_start=2, s_end=7, sol_section_start=7, solution_pdf_path=? "
            "WHERE id=?", (str(split), pid))
        conn.commit()
    finally:
        conn.close()
    _mock_apps(monkeypatch)
    out = run_pipeline(pid, force=True)
    assert out["status"] == "done"
    assert not split.exists()
    row = database.get_paper(pid)
    assert row["solution_pdf_path"] == row["question_pdf_path"]


def test_run_pipeline_unknown_paper(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    _mock_apps(monkeypatch)
    with pytest.raises(ValueError, match="does not exist"):
        run_pipeline(99999)


def test_summarize_tokens_math(tmp_db, tmp_path, monkeypatch):
    import config

    pid = _reg(tmp_db, tmp_path)
    database.log_token_usage(pid, "indexer", input_tokens=1000,
                             cache_read=600, output_tokens=100, reasoning_tokens=40)
    database.log_token_usage(pid, "extractor", input_tokens=500,
                             cache_read=100, output_tokens=50, reasoning_tokens=10)
    monkeypatch.setattr(config, "PRICING", {
        "input_per_mtok": 2.0, "cache_read_per_mtok": 0.5, "output_per_mtok": 10.0})
    s = summarize_tokens(pid)
    assert s["per_phase"]["indexer"]["turns"] == 1
    assert s["per_phase"]["extractor"]["input"] == 500
    assert s["total"]["fresh_input"] == (1000 - 600) + (500 - 100)
    assert s["total"]["reasoning"] == 50
    # cost = 800/1e6*2 + 700/1e6*0.5 + 150/1e6*10
    assert abs(s["cost_usd"] - (0.0016 + 0.00035 + 0.0015)) < 1e-9


def test_run_indexer_sets_status_flow(tmp_db, tmp_path, monkeypatch):
    """Standalone indexer: indexing during run, uploaded queue after."""
    import run_indexer as ri_mod

    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")

    class FakePhase1:
        def invoke(self, state, config=None):
            assert database.get_paper(state["paper_id"])["status"] == "indexing"
            return {"status": "indexer_complete"}

    monkeypatch.setattr(ri_mod, "phase1_app", FakePhase1())
    assert ri_mod.main([str(q)]) == 0
    row = database.get_paper(1)
    assert row["status"] == "uploaded"
    assert row["q_start"] is None  # mocked app writes nothing; status only


def test_run_indexer_abort_marks_failed(tmp_db, tmp_path, monkeypatch):
    """Standalone indexer: no-text abort lands in failed, not queued."""
    import run_indexer as ri_mod

    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")

    class FakeAbort:
        def invoke(self, state, config=None):
            return {"status": "aborted_no_text"}

    monkeypatch.setattr(ri_mod, "phase1_app", FakeAbort())
    assert ri_mod.main([str(q)]) == 0
    row = database.get_paper(1)
    assert row["status"] == "failed" and "text layer" in (row["error"] or "")


def test_run_indexer_refuses_done_paper(tmp_db, tmp_path, monkeypatch):
    """Re-running the indexer over a done paper leaves it done."""
    import run_indexer as ri_mod

    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")

    class FakePhase1:
        def invoke(self, state, config=None):  # pragma: no cover
            raise AssertionError("must not run")

    monkeypatch.setattr(ri_mod, "phase1_app", FakePhase1())
    pid = database.register_paper(str(q))
    database.set_paper_status(pid, "done")
    assert ri_mod.main([str(q)]) == 1
    assert database.get_paper(pid)["status"] == "done"


def test_run_indexer_crash_marks_failed(tmp_db, tmp_path, monkeypatch):
    """Standalone indexer: exception records failed + error."""
    import run_indexer as ri_mod

    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")

    class FakeCrash:
        def invoke(self, state, config=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(ri_mod, "phase1_app", FakeCrash())
    assert ri_mod.main([str(q)]) == 1
    row = database.get_paper(1)
    assert row["status"] == "failed" and "boom" in (row["error"] or "")


def test_run_extractor_done_and_missing(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    """Standalone extractor: full coverage -> done; gaps -> failed."""
    import directory_manager as dm
    import run_extractor as re_mod

    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")
    pid = database.register_paper(str(q))
    conn = database.get_connection()
    try:
        conn.execute(
            "UPDATE papers SET q_start=1, q_end=1, s_start=1, s_end=1 WHERE id=?",
            (pid,),
        )
        conn.commit()
    finally:
        conn.close()

    class FakeExt:
        def invoke(self, state, config=None):
            return {"status": "extractor_complete", "messages": []}

    monkeypatch.setattr(re_mod, "extractor_app", FakeExt())
    # Nothing submitted yet: coverage finds no questions -> done (no gaps).
    assert re_mod.main([str(pid)]) == 0
    assert database.get_paper(pid)["status"] == "done"

    # A question dir with question.tex but no solution.tex -> failed.
    qdir = dm.ensure_question_dir(pid, "1")
    (qdir / dm.QUESTION_TEX).write_text("q")
    database.set_paper_status(pid, "uploaded")
    assert re_mod.main([str(pid)]) == 0
    row = database.get_paper(pid)
    assert row["status"] == "failed" and "1" in (row["error"] or "")


def test_graph_loop_logs_token_rows(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    """_run_agent_turn appends one token_usage row per AI message."""
    import graph

    pid = _reg(tmp_db, tmp_path)

    class FakeLLM:
        def bind_tools(self, tools, **kwargs):
            return self

        def invoke(self, messages):
            return AIMessage(
                content="hi",
                usage_metadata={"input_tokens": 11, "output_tokens": 3,
                                "total_tokens": 14,
                                "input_token_details": {"cache_read": 7},
                                "output_token_details": {"reasoning": 1}},
            )

    monkeypatch.setattr(graph, "get_llm", lambda: FakeLLM())
    state = graph.initial_state(pid, "q.pdf", "s.pdf")
    graph.indexer_node(state)
    rows = database.get_connection().execute(
        "SELECT phase, input, cache_read, output, reasoning FROM token_usage"
    ).fetchall()
    assert len(rows) == 1
    assert tuple(rows[0]) == ("indexer", 11, 7, 3, 1)
