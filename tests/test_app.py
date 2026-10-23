"""App helper tests: pairing, tex preprocessing, tex->png fallback."""
from __future__ import annotations

import pytest

from app.pairing import auto_pair, stem


def test_stem_normalizes():
    assert stem("GTA-01_QP.pdf") == "gta 01 qp"
    assert stem("GTA-01_Key & Sols.pdf") == "gta 01 &"
    assert stem("JEE 2024 Paper 1 Solutions.pdf") == "jee 2024 paper 1"
    assert stem("monkey business.pdf") == "monkey business"  # no inner-word strip


def test_auto_pair_gta_style():
    pairs = auto_pair(["GTA-01_QP.pdf", "GTA-02_QP.pdf"],
                      ["GTA-01_Key & Sols.pdf", "GTA-02_Key & Sols.pdf"])
    assert pairs == [("GTA-01_QP.pdf", "GTA-01_Key & Sols.pdf"),
                     ("GTA-02_QP.pdf", "GTA-02_Key & Sols.pdf")]


def test_auto_pair_unmatched_gets_none():
    assert auto_pair(["QP.pdf"], []) == [("QP.pdf", None)]
    pairs = auto_pair(["AAA_QP.pdf"], ["ZZZ_Solutions.pdf"])
    # very dissimilar names stay unpaired rather than forced
    assert pairs == [("AAA_QP.pdf", None)]


def test_tex_to_markdown_basics():
    from app.render import tex_to_markdown

    out = tex_to_markdown(r"\textbf{A)} $\sigma$ \hspace{2cm} 50\% sure \& done")
    assert "**A)**" in out and r"$\sigma$" in out and "50% sure & done" in out
    assert "hspace" not in out


def test_tex_comments_key_line_kept_rest_dropped():
    from app.render import tex_to_markdown

    out = tex_to_markdown("% Answer: 21-B\n21. Real solution $x=1$ here.\n% a note\ntrailing % cut")
    assert "% Answer" not in out
    assert "**Answer:** 21-B" in out
    assert "no_solution_found" not in out and "a note" not in out
    assert out.rstrip().endswith("trailing")


def test_tex_underline_heading_survives():
    from app.render import tex_to_markdown

    out = tex_to_markdown("\\underline{\\textbf{Solution for 29}}")
    assert out == "$\\underline{\\textbf{Solution for 29}}$"
    # No raw HTML: Streamlit escapes it, KaTeX renders the math form.
    assert "<u>" not in out


def test_tex_stray_dollar_escaped_not_paired():
    from app.render import tex_to_markdown

    out = tex_to_markdown("cost is $5 and $x=1$ ok")
    # "$5 and ..." must not open a math span; the real pair survives
    assert "$x=1$" in out
    assert "cost is $5 and" in out


def test_tex_escaped_dollar_stays_literal():
    from app.render import tex_to_markdown

    out = tex_to_markdown(r"pay \$5 for $x$")
    assert "$x$" in out and "pay $5 for" in out


def test_tex_keeps_spaces_around_inline_math():
    from app.render import tex_to_markdown

    out = tex_to_markdown("scales: $m_1L_1=m_2L_2$ Since then")
    assert "scales: $m_1L_1=m_2L_2$ Since then" in out


def test_tex_preserves_paragraph_breaks():
    from app.render import tex_to_markdown

    out = tex_to_markdown("First para $x=1$.\n\nSecond para $y=2$.")
    assert "First para $x=1$.\n\nSecond para $y=2$." in out


def test_tex_display_brackets_become_dollars():
    from app.render import tex_to_markdown

    out = tex_to_markdown(r"if \[ V_1L_1=V_2L_2 \] Divide")
    assert r"\[" not in out
    assert "$$V_1L_1=V_2L_2$$" in out


def test_tex_dfrac_tamed_only_inline():
    from app.render import tex_to_markdown

    out = tex_to_markdown(r"a $\dfrac{m_1}{V_1}$ b $$ \dfrac{x}{y} $$ c")
    assert r"$\frac{m_1}{V_1}$" in out  # inline: tamed
    assert r"\dfrac{x}{y}" in out  # display: left alone


def test_split_tex_extracts_figures(tmp_path):
    from app.render import split_tex

    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "fig1.png").write_bytes(b"fake")
    segs = split_tex(
        "Intro.\n\\includegraphics[width=0.3\\linewidth]{figures/fig1.png}\nOutro $x$.",
        tmp_path)
    kinds = [k for k, _ in segs]
    assert kinds == ["text", "fig", "text"]
    assert segs[1][1].endswith("figures/fig1.png")
    assert "$x$" in segs[2][1]


def test_split_tex_missing_figure_flagged(tmp_path):
    from app.render import split_tex

    segs = split_tex(r"See \includegraphics{figures/ghost.png}.", tmp_path)
    assert segs[1] == ("fig", "")


def test_render_question_image_if_engine(tmp_path):
    from app.render import render_tex_to_png, tex_engine_available

    if not tex_engine_available():
        pytest.skip("no working tectonic bundle here")
    qdir = tmp_path / "q"
    qdir.mkdir()
    out = render_tex_to_png(r"Hello $E=mc^2$.", qdir, "_q.png")
    assert out is not None and out.is_file() and out.stat().st_size > 1000
    # Cached second call returns the same file without recompiling.
    assert render_tex_to_png(r"Hello $E=mc^2$.", qdir, "_q.png") == out


def test_render_with_figure_stages_it_for_compile(tmp_path):
    """Regression: \\includegraphics must resolve (tectonic sandboxes to cwd)."""
    from PIL import Image as PILImage

    from app.render import render_tex_to_png, tex_engine_available

    if not tex_engine_available():
        pytest.skip("no working tectonic bundle here")
    qdir = tmp_path / "q"
    (qdir / "figures").mkdir(parents=True)
    PILImage.new("RGB", (60, 40), "white").save(str(qdir / "figures" / "a.png"))
    out = render_tex_to_png(r"See \includegraphics{figures/a.png} here.", qdir, "_q.png")
    assert out is not None and out.is_file() and out.stat().st_size > 1000


def test_vertical_trim_keeps_width_drops_dead_bands():
    """Unit: trim kills top/bottom whitespace, keeps full width + padding."""
    from PIL import Image as PILImage

    from app.render import _TRIM_PAD, _trim_vertical_whitespace

    img = PILImage.new("RGB", (200, 400), "white")
    px = img.load()
    for y in range(50, 101):
        for x in range(20, 181):
            px[x, y] = (0, 0, 0)
    out = _trim_vertical_whitespace(img)
    assert out.width == 200
    assert out.height == (100 - 50 + 1) + 2 * _TRIM_PAD
    # All-white page is returned untouched.
    blank = PILImage.new("RGB", (200, 400), "white")
    assert _trim_vertical_whitespace(blank).size == (200, 400)


def test_split_candidates_uses_word_boundary_rule():
    from app.pairing import is_solution_name, split_candidates

    assert is_solution_name("GTA-01_Key & Sols.pdf")
    assert is_solution_name("JEE 2024 Paper 1 Solutions.pdf")
    assert not is_solution_name("GTA-01_QP.pdf")
    # "sol" inside a longer word must NOT count as a solution file.
    assert not is_solution_name("Consolidation_QP.pdf")
    q, s = split_candidates(["GTA-01_QP.pdf", "GTA-01_Key & Sols.pdf",
                             "Consolidation_QP.pdf"])
    assert q == ["GTA-01_QP.pdf", "Consolidation_QP.pdf"]
    assert s == ["GTA-01_Key & Sols.pdf"]


def _managed_pair(tmp_path, monkeypatch, tag="T"):
    """Register a pair under a fake DATA_ROOT; return (pid, q, s, root)."""
    import database
    import directory_manager

    root = tmp_path / "data"
    (root / "uploads").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(directory_manager, "DATA_ROOT", root)
    q = root / "uploads" / f"{tag}_QP.pdf"
    s = root / "uploads" / f"{tag}_Key.pdf"
    q.write_bytes(b"Q" + tag.encode())
    s.write_bytes(b"S" + tag.encode())
    pid = database.register_paper(str(q), str(s))
    return pid, q, s, root


def test_update_paper_paths_roundtrip(tmp_db, tmp_path):
    import database

    q = tmp_path / "q.pdf"
    s = tmp_path / "s.pdf"
    q.write_bytes(b"Q")
    s.write_bytes(b"S")
    pid = database.register_paper(str(q), str(s))
    database.update_paper_paths(pid, "nq.pdf", "ns.pdf")
    row = database.get_paper(pid)
    assert (row["question_pdf_path"], row["solution_pdf_path"]) == ("nq.pdf", "ns.pdf")
    with pytest.raises(ValueError):
        database.update_paper_paths(9999, "a", "b")


def test_relocate_managed_moves_and_updates_db(tmp_db, tmp_path, monkeypatch):
    import database
    from app.pairing import relocate_managed_files

    pid, q, s, root = _managed_pair(tmp_path, monkeypatch)
    assert relocate_managed_files(pid, root / "processing") is True
    row = database.get_paper(pid)
    assert row["question_pdf_path"] == str(root / "processing" / q.name)
    assert row["solution_pdf_path"] == str(root / "processing" / s.name)
    assert not q.exists() and (root / "processing" / q.name).is_file()


def test_relocate_leaves_unmanaged_paths(tmp_db, tmp_path, monkeypatch):
    import database
    import directory_manager
    from app.pairing import relocate_managed_files

    monkeypatch.setattr(directory_manager, "DATA_ROOT", tmp_path / "data")
    q = tmp_path / "elsewhere_q.pdf"
    s = tmp_path / "elsewhere_s.pdf"
    q.write_bytes(b"Q")
    s.write_bytes(b"S")
    pid = database.register_paper(str(q), str(s))
    assert relocate_managed_files(pid, tmp_path / "data" / "processing") is False
    assert database.get_paper(pid)["question_pdf_path"] == str(q)


def test_reconcile_deletes_missing_non_done_keeps_done(tmp_db, tmp_path, monkeypatch):
    import database
    import directory_manager
    from app.pairing import reconcile_missing_sources

    monkeypatch.setattr(directory_manager, "DATA_ROOT", tmp_path / "data")
    (tmp_path / "data" / "uploads").mkdir(parents=True)
    q1 = tmp_path / "data" / "uploads" / "A_QP.pdf"
    q2 = tmp_path / "data" / "uploads" / "B_QP.pdf"
    q1.write_bytes(b"A")
    q2.write_bytes(b"B")
    p1 = database.register_paper(str(q1), None)
    p2 = database.register_paper(str(q2), None)
    database.set_paper_status(p2, "done")
    q1.unlink()  # offline delete of a live paper
    assert reconcile_missing_sources() == [p1]
    assert database.get_paper(p1) is None
    assert database.get_paper(p2) is not None


def test_delete_paper_everywhere(tmp_db, tmp_path, tmp_outputs, monkeypatch):
    import database
    import directory_manager
    from app.pairing import delete_paper_everywhere

    pid, q, s, root = _managed_pair(tmp_path, monkeypatch, tag="D")
    qdir = directory_manager.ensure_question_dir(pid, "1")
    (qdir / "question.tex").write_text("x")
    outside = tmp_path / "keep.pdf"
    outside.write_bytes(b"K")
    database.update_paper_paths(pid, str(q), str(outside))
    assert delete_paper_everywhere(pid) is True
    assert database.get_paper(pid) is None
    assert not q.exists()  # managed pdf removed
    assert outside.is_file()  # outside file untouched
    assert not qdir.exists()  # Outputs cleaned
    assert delete_paper_everywhere(pid) is False


def test_render_recompiles_when_figure_bytes_change(tmp_path):
    """Regression: figure swaps must bust the tex-hash PNG cache."""
    from pathlib import Path as _Path

    from PIL import Image as PILImage

    from app.render import render_tex_to_png, tex_engine_available

    if not tex_engine_available():
        pytest.skip("no working tectonic bundle here")
    qdir = tmp_path / "q"
    (qdir / "figures").mkdir(parents=True)
    fig = qdir / "figures" / "a.png"
    PILImage.new("RGB", (60, 40), "white").save(str(fig))
    tex = r"See \includegraphics{figures/a.png} here."
    out = render_tex_to_png(tex, qdir, "_q.png")
    assert out is not None
    marker = _Path(str(out) + ".src_hash")
    before = marker.read_text()
    first_bytes = out.read_bytes()
    PILImage.new("RGB", (60, 40), "black").save(str(fig))
    out2 = render_tex_to_png(tex, qdir, "_q.png")
    assert out2 is not None
    assert marker.read_text() != before
    assert out2.read_bytes() != first_bytes


def test_registry_background_lifecycle():
    """Unit: submit/poll/clear across threads without streamlit."""
    import threading
    import time

    from app.runs import RunRegistry

    reg = RunRegistry(max_workers=1)
    started = threading.Event()

    def job(pid):
        started.set()
        time.sleep(0.2)
        return (pid, "done", 1.5)

    assert reg.submit(7, job, 7) is True
    assert reg.submit(7, job, 7) is False  # in flight: rejected
    assert reg.running() == [7]
    assert started.wait(timeout=5)
    deadline = time.time() + 5
    while not reg.completed() and time.time() < deadline:
        time.sleep(0.05)
    assert reg.completed() == [(7, "done", 1.5)]
    assert reg.clear_finished() == 1
    assert reg.running() == [] and reg.completed() == []
    assert reg.submit(7, job, 7) is True  # resubmittable after finish


def test_registry_error_and_batch_shapes():
    import time

    from app.runs import RunRegistry

    reg = RunRegistry(max_workers=2)

    def boom(pid):
        raise RuntimeError("kaput")

    def batch(ids):
        return [(i, "done", 1.0) for i in ids]

    assert reg.submit(9, boom, 9) is True
    assert reg.submit(("seq", (1, 2)), batch, (1, 2)) is True
    deadline = time.time() + 5
    while len(reg.completed()) < 3 and time.time() < deadline:
        time.sleep(0.05)
    rows = sorted(reg.completed(), key=repr)
    assert (9, "error", "RuntimeError: kaput") in rows
    assert (1, "done", 1.0) in rows and (2, "done", 1.0) in rows


def test_reset_stuck_running(tmp_db, tmp_path):
    import database

    q1 = tmp_path / "a.pdf"
    q2 = tmp_path / "b.pdf"
    q1.write_bytes(b"A")
    q2.write_bytes(b"B")
    p1 = database.register_paper(str(q1), None)
    p2 = database.register_paper(str(q2), None)
    database.set_paper_status(p1, "indexing")
    database.set_paper_status(p2, "done")
    assert database.reset_stuck_running() == [p1]
    row = database.get_paper(p1)
    assert row["status"] == "failed" and "restart" in row["error"]
    assert database.reset_stuck_running() == []


def test_relocate_is_idempotent_and_adopts_identical_dest(tmp_db, tmp_path, monkeypatch):
    """Second relocate is a no-op; identical dest files are adopted, not duped."""
    import database
    import directory_manager
    from app.pairing import relocate_managed_files

    pid, q, s, root = _managed_pair(tmp_path, monkeypatch, tag="I")
    proc = root / "processing"
    assert relocate_managed_files(pid, proc) is True
    assert relocate_managed_files(pid, proc) is False  # already in place
    row = database.get_paper(pid)
    assert row["question_pdf_path"] == str(proc / q.name)

    # Identical bytes pre-seeded at dest: adopted, original cleaned up.
    pid2, q2, s2, _ = _managed_pair(tmp_path, monkeypatch, tag="J")
    (proc / q2.name).write_bytes(q2.read_bytes())
    (proc / s2.name).write_bytes(s2.read_bytes())
    assert relocate_managed_files(pid2, proc) is True
    assert not q2.exists() and (proc / q2.name).is_file()
    assert database.get_paper(pid2)["question_pdf_path"] == str(proc / q2.name)


def test_llm_retry_rides_through_429_then_succeeds():
    from llm import invoke_with_retry

    class Fake429(Exception):
        status_code = 429

    calls = []

    class FakeLLM:
        def invoke(self, messages):
            calls.append(1)
            if len(calls) < 3:
                raise Fake429("slow down")
            return "ok"

    sleeps = []
    out = invoke_with_retry(FakeLLM(), [], max_attempts=5, base_sec=10.0,
                            budget_sec=600.0, _sleep=sleeps.append)
    assert out == "ok" and len(calls) == 3 and len(sleeps) == 2
    assert sleeps[0] < sleeps[1]  # exponential growth (gap 10s >> jitter)


def test_llm_retry_gives_up_and_reraises():
    import pytest as _pytest

    from llm import invoke_with_retry

    class Fake429(Exception):
        status_code = 429

    calls = []

    class FakeLLM:
        def invoke(self, messages):
            calls.append(1)
            raise Fake429("still limited")

    sleeps = []
    with _pytest.raises(Fake429):
        invoke_with_retry(FakeLLM(), [], max_attempts=3, base_sec=0.001,
                          budget_sec=60.0, _sleep=sleeps.append)
    assert len(calls) == 3 and len(sleeps) == 2


def test_llm_retry_fast_fails_non_retryable():
    import pytest as _pytest

    from llm import invoke_with_retry

    class Fake401(Exception):
        status_code = 401

    calls = []

    class FakeLLM:
        def invoke(self, messages):
            calls.append(1)
            raise Fake401("bad key")

    sleeps = []
    with _pytest.raises(Fake401):
        invoke_with_retry(FakeLLM(), [], max_attempts=5, base_sec=0.001,
                          budget_sec=60.0, _sleep=sleeps.append)
    assert len(calls) == 1 and sleeps == []


def test_llm_retry_honors_retry_after_and_budget():
    from llm import invoke_with_retry

    class Fake429(Exception):
        status_code = 429
        response = type("Resp", (), {"headers": {"retry-after": "30"}})()

    class FakeLLM:
        def invoke(self, messages):
            raise Fake429("slow down")

    sleeps = []
    try:
        invoke_with_retry(FakeLLM(), [], max_attempts=2, base_sec=0.001,
                          budget_sec=60.0, _sleep=sleeps.append)
    except Fake429:
        pass
    assert len(sleeps) == 1 and sleeps[0] >= 30.0

    # Budget clamps an unbounded storm: huge backoff, tiny budget.
    sleeps2 = []
    try:
        invoke_with_retry(FakeLLM(), [], max_attempts=100, base_sec=60.0,
                          budget_sec=10.0, _sleep=sleeps2.append)
    except Fake429:
        pass
    assert sum(sleeps2) <= 10.0 + 1e-9


def test_llm_retryable_matches_real_openai_errors():
    import httpx
    import openai

    from llm import _is_retryable

    def err(cls, status):
        req = httpx.Request("POST", "https://api.meta.ai/v1/chat/completions")
        return cls("boom", response=httpx.Response(status, request=req), body={})

    assert _is_retryable(err(openai.RateLimitError, 429)) is True
    assert _is_retryable(err(openai.InternalServerError, 500)) is True
    assert _is_retryable(err(openai.AuthenticationError, 401)) is False
    assert _is_retryable(err(openai.BadRequestError, 400)) is False


def _fig_qdir(tmp_path):
    from pathlib import Path as _P

    qdir = _P(tmp_path) / "q"
    (qdir / "figures").mkdir(parents=True)
    return qdir


def test_figure_helpers_list_side_next(tmp_path):
    from PIL import Image as _PIL

    from app.figures import figure_side, list_figures, next_figure_name

    qdir = _fig_qdir(tmp_path)
    _PIL.new("RGB", (10, 10), "white").save(str(qdir / "figures" / "qfig1.png"))
    _PIL.new("RGB", (10, 10), "white").save(str(qdir / "figures" / "sfig1.png"))
    (qdir / "figures" / "_provenance.json").write_text("{}")
    (qdir / "figures" / "notes.txt").write_text("x")
    names = [p.name for p in list_figures(qdir)]
    assert names == ["qfig1.png", "sfig1.png"]
    assert figure_side("qfig2.png") == "question"
    assert figure_side("sfig9.png") == "solution"
    assert figure_side("fig1.png") == "legacy"
    assert next_figure_name(qdir, "question") == "qfig2.png"
    assert next_figure_name(qdir, "solution") == "sfig2.png"


def test_figure_ref_insert_remove_roundtrip():
    from app.figures import insert_figure_ref, remove_figure_refs

    tex = "Hello $x$.\n\\begin{center}\n\\includegraphics{figures/qfig1.png}\n\\end{center}\nTail.\n"
    new, n = remove_figure_refs(tex, "qfig1.png")
    assert n == 1 and "qfig1" not in new and "Tail." in new
    assert "\\begin{center}" not in new  # lone env eaten too
    added = insert_figure_ref("Body.\n", "qfig2.png")
    assert added.count("qfig2.png") == 1 and added.startswith("Body.")
    unchanged, n0 = remove_figure_refs("No figs here.\n", "qfig9.png")
    assert (unchanged, n0) == ("No figs here.\n", 0)


def test_crop_image_file_shrinks_and_rejects_degenerate(tmp_path):
    import pytest as _pytest
    from PIL import Image as _PIL

    from app.figures import crop_image_file

    qdir = _fig_qdir(tmp_path)
    p = qdir / "figures" / "qfig1.png"
    _PIL.new("RGB", (100, 80), "white").save(str(p))
    crop_image_file(p, (0.1, 0.1, 0.9, 0.9))
    assert _PIL.open(p).size == (80, 64)
    with _pytest.raises(ValueError):
        crop_image_file(p, (0.5, 0.5, 0.5, 0.9))


def test_save_uploaded_figure_validates(tmp_path):
    import io as _io

    import pytest as _pytest
    from PIL import Image as _PIL

    from app.figures import save_uploaded_figure

    qdir = _fig_qdir(tmp_path)
    buf = _io.BytesIO()
    _PIL.new("RGB", (10, 10), "white").save(buf, format="PNG")
    dest = save_uploaded_figure(qdir, "qfig1.png", buf.getvalue())
    assert dest.is_file()
    with _pytest.raises(ValueError):
        save_uploaded_figure(qdir, "qfig1.png", buf.getvalue())  # duplicate
    with _pytest.raises(ValueError):
        save_uploaded_figure(qdir, "../evil.png", buf.getvalue())
    with _pytest.raises(ValueError):
        save_uploaded_figure(qdir, "qfig2.png", b"not an image")


def test_ui_edited_tex_still_submits(tmp_db, tmp_path, tmp_outputs):
    """Simulate UI flows: attach ref -> submit saves; remove ref -> still saves."""
    import database
    import directory_manager
    from app.figures import (insert_figure_ref, list_figures,
                             remove_figure_refs, save_uploaded_figure)
    from tools_extractor import submit_question

    q = tmp_path / "q.pdf"
    q.write_bytes(b"Q")
    pid = database.register_paper(str(q), None)
    qdir = directory_manager.ensure_question_dir(pid, "1")
    import io as _io

    from PIL import Image as _PIL

    buf = _io.BytesIO()
    _PIL.new("RGB", (10, 10), "white").save(buf, format="PNG")
    save_uploaded_figure(qdir, "qfig1.png", buf.getvalue())
    assert [p.name for p in list_figures(qdir)] == ["qfig1.png"]
    tex = insert_figure_ref("Body.\n", "qfig1.png")
    assert submit_question.invoke(
        {"paper_id": pid, "question_number": "1", "latex_content": tex}) == "saved"
    trimmed, n = remove_figure_refs(tex, "qfig1.png")
    assert n == 1
    assert submit_question.invoke(
        {"paper_id": pid, "question_number": "1", "latex_content": trimmed}) == "saved"
