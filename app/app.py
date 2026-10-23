"""PaperLab: three-stage UI (Upload & verify / Processing / Paper library)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import config  # noqa: F401  (pins env first)
import database
import directory_manager
from app.library import bucket_papers, display_name, exam_options, filter_papers
from app.pairing import UPLOAD_DIR, auto_pair, register_pair, save_uploads
from app.reader import neighbor_ids, paper_title, question_ids
from app.render import render_tex_to_png, split_tex, tex_engine_available
from run_pipeline import run_pipeline, summarize_tokens

st.set_page_config(page_title="PaperLab", page_icon="📄", layout="wide")
database.init_db()

st.title("PaperLab")
st.caption("Question bank · Mathematics & CS")

stage = st.sidebar.radio(
    "Stage",
    ["01 · Upload & verify", "02 · Processing", "03 · Paper library", "Admin"],
    key="stage",
)


# ------------------------------------------------- shared data access ---


def _all_papers():
    conn = database.get_connection()
    try:
        return conn.execute("SELECT * FROM papers ORDER BY id DESC").fetchall()
    finally:
        conn.close()


def _paper_questions(pid: int):
    conn = database.get_connection()
    try:
        return conn.execute(
            "SELECT question_number FROM questions WHERE paper_id = ? ORDER BY id",
            (pid,)).fetchall()
    finally:
        conn.close()


def _show_figure(path: str) -> None:
    """Show a figure at natural size, capped so small diagrams stay small."""
    from PIL import Image

    try:
        w = Image.open(path).size[0]
    except Exception:
        w = 700
    st.image(path, caption=Path(path).name, width=min(w, 700))


def _render_tex_block(tex: str, base_dir: Path, key: str, label: str) -> None:
    for kind, payload in split_tex(tex, base_dir):
        if kind == "fig":
            if payload:
                _show_figure(payload)
            else:
                st.warning("Referenced figure file is missing on disk.")
        elif payload:
            st.markdown(payload)
    if tex_engine_available():
        if st.button(f"Render {label} as image", key=f"tex_{key}"):
            out = render_tex_to_png(tex, base_dir, f"_{label}.png")
            if out is not None:
                st.image(str(out), caption=f"{label} (compiled TeX)")
            else:
                st.error("TeX compile failed here; the view above stands.")


# ------------------------------------------------- 01 Upload & verify ---


def stage_upload() -> None:
    st.header("01 · Upload & verify")
    st.caption("Nothing enters processing until you explicitly confirm the pairs.")
    q_files = st.file_uploader("Question PDFs", type="pdf", accept_multiple_files=True,
                               key="up_q")
    s_files = st.file_uploader("Solution PDFs", type="pdf", accept_multiple_files=True,
                               key="up_s")
    if st.button("Stage files"):
        nq = len(save_uploads(q_files or []))
        ns = len(save_uploads(s_files or []))
        st.success(f"Staged {nq} question + {ns} solution PDFs.")

    staged = sorted(p.name for p in UPLOAD_DIR.glob("*.pdf")) if UPLOAD_DIR.is_dir() else []
    if not staged:
        st.info("Upload PDFs above, then stage them for pairing.")
        return
    rm = st.multiselect("Remove mistaken uploads (does not touch registered papers)",
                        staged, key="rm_staged")
    c_rm, c_clr = st.columns(2)
    if c_rm.button("Delete selected", disabled=not rm):
        for n in rm:
            (UPLOAD_DIR / n).unlink(missing_ok=True)
        st.rerun()
    if c_clr.button("Clear staging area"):
        for p in UPLOAD_DIR.glob("*.pdf"):
            p.unlink()
        st.rerun()
    staged = [n for n in staged if n not in rm]
    st.divider()
    st.subheader("Verify pairs")
    st.caption("Auto-matched by filename — correct any mismatch before confirming.")
    q_names = [n for n in staged if "sol" not in n.lower() and "key" not in n.lower()]
    s_names = [n for n in staged if n not in q_names]
    for n in staged:
        if n not in q_names and n not in s_names:
            q_names.append(n)
    pairs = auto_pair(q_names, s_names)
    final = []
    for i, (q, s_default) in enumerate(pairs):
        c1, c2 = st.columns([1, 1])
        c1.write(f"**{q}**")
        options = ["— none —"] + s_names
        idx = options.index(s_default) if s_default in options else 0
        s_choice = c2.selectbox("Solution PDF", options, index=idx, key=f"pair_{i}")
        final.append((q, None if s_choice == "— none —" else s_choice))

    if st.button("Confirm pairs & register", type="primary"):
        for q, s in final:
            pid, reused = register_pair(str(UPLOAD_DIR / q),
                                        str(UPLOAD_DIR / s) if s else None)
            if reused:
                st.info(f"#{pid} {q}: already registered — identified, not re-queued.")
            else:
                st.success(f"Confirmed paper_id={pid}: {q}" + (f" + {s}" if s else ""))


# ------------------------------------------------------- 02 Processing ---


def stage_processing() -> None:
    st.header("02 · Processing")
    st.caption("Only confirmed pairs. Done papers never re-enter except by explicit rerun.")
    buckets = bucket_papers(_all_papers())

    if buckets["running"]:
        st.subheader("Running")
        for r in buckets["running"]:
            st.write(f"#{r['id']} · {display_name(r)} · `{r['status']}` …")
        if st.button("Refresh"):
            st.rerun()
    st.subheader("Queue")
    queue = buckets["queued"] + buckets["failed"]
    if not queue:
        st.info("Queue is empty — confirm pairs on the Upload page.")
    else:
        for r in queue:
            extra = f" — {r['error']}" if r["status"] == "failed" else ""
            st.write(f"#{r['id']} · {display_name(r)} · `{r['status']}`{extra}")

    sel = st.multiselect("Run papers (explicit selection only — nothing runs by itself)",
                         [f"#{r['id']} · {display_name(r)}" for r in queue],
                         default=[])
    ids = [int(s.split()[0][1:]) for s in sel]
    mode = st.radio("Mode", ["One by one (sequential)", "All in parallel"], horizontal=True)
    force = st.checkbox("Force rerun (wipes outputs + rows first)")

    def _run(pid: int):
        try:
            out = run_pipeline(pid, force=force)
            return pid, out["status"], out["elapsed_sec"]
        except Exception as exc:  # noqa: BLE001 -- surfaced per paper
            return pid, "error", str(exc)

    if st.button("Run", type="primary", disabled=not ids):
        if mode.startswith("One"):
            progress = st.progress(0.0)
            results = []
            for i, pid in enumerate(ids):
                results.append(_run(pid))
                progress.progress((i + 1) / len(ids))
        else:
            with ThreadPoolExecutor(max_workers=3) as pool:
                results = [f.result() for f in
                           as_completed([pool.submit(_run, pid) for pid in ids])]
        for pid, status, info in sorted(results):
            if status == "error":
                st.error(f"paper {pid}: {info}")
            else:
                st.write(f"paper {pid}: {status} ({info:.1f}s)")
    with st.expander("History (completed)"):
        for r in bucket_papers(_all_papers())["done"]:
            st.write(f"#{r['id']} · {display_name(r)} · done")


# ----------------------------------------------------------- 03 Library ---


def stage_library() -> None:
    st.header("03 · Paper library")
    papers = [r for r in _all_papers() if (r["status"] or "") == "done"]
    show_all = st.checkbox("Include unfinished papers", value=False)
    if show_all:
        papers = _all_papers()
    query = st.text_input("Search papers", placeholder="fuzzy search by name…")
    exams = ["All"] + exam_options(papers if show_all else _all_papers())
    exam = st.selectbox("Exam", exams)
    papers = filter_papers(papers, query, exam)
    if not papers:
        st.info("No completed papers yet — process some on the Processing page.")
        return
    for r in papers:
        nq = database.get_connection().execute(
            "SELECT COUNT(*) FROM questions WHERE paper_id = ?",
            (r["id"],)).fetchone()[0]
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"### {r['paper_name'] or f'Paper {r['id']}'}")
            c1.caption(f"{r['exam_type'] or 'Unknown exam'} · "
                       f"{r['paper_date'] or 'undated'} · "
                       f"{nq} questions · #{r['id']}")
            if c2.button("Open", key=f"lib_{r['id']}", width="stretch"):
                st.session_state["paper"] = r["id"]
                st.session_state["q"] = None
                st.session_state["show_ans"] = False
    _reader()


def _reader() -> None:
    pid = st.session_state.get("paper")
    if pid is None:
        return
    conn = database.get_connection()
    try:
        paper = conn.execute("SELECT * FROM papers WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    if paper is None:
        return
    st.divider()
    st.caption(paper_title(paper))
    ids = question_ids(_paper_questions(pid))
    if not ids:
        st.info("No questions submitted for this paper yet.")
        return
    if st.session_state.get("q") not in ids:
        st.session_state["q"] = ids[0]
    nav, reading = st.columns([1, 3])
    with nav:
        st.caption("Questions")
        for qn in ids:
            if st.button(qn, key=f"nav_{pid}_{qn}", width="stretch"):
                st.session_state["q"] = qn
                st.session_state["show_ans"] = False
    with reading:
        qn = st.session_state["q"]
        qdir = directory_manager.get_question_dir(pid, qn)
        st.subheader(f"Question {qn}")
        with st.container():
            qtex = (qdir / "question.tex").read_text(encoding="utf-8") \
                if (qdir / "question.tex").is_file() else "*missing*"
            _render_tex_block(qtex, qdir, f"{pid}_{qn}_q", "question")
        if st.button("Show solution" if not st.session_state.get("show_ans")
                     else "Hide solution", key=f"ans_{pid}_{qn}"):
            st.session_state["show_ans"] = not st.session_state.get("show_ans")
        if st.session_state.get("show_ans"):
            stex = (qdir / "solution.tex").read_text(encoding="utf-8") \
                if (qdir / "solution.tex").is_file() else "*missing*"
            _render_tex_block(stex, qdir, f"{pid}_{qn}_s", "solution")
        prev_id, next_id = neighbor_ids(ids, qn)
        p1, p2, p3 = st.columns([1, 1, 2])
        if p1.button("← Previous", key=f"prev_{pid}_{qn}", disabled=prev_id is None):
            st.session_state["q"] = prev_id
            st.session_state["show_ans"] = False
            st.rerun()
        if p2.button("Next →", key=f"nxt_{pid}_{qn}", disabled=next_id is None):
            st.session_state["q"] = next_id
            st.session_state["show_ans"] = False
            st.rerun()
        jump = p3.selectbox("Jump to", ids, index=ids.index(qn))
        if jump != qn:
            st.session_state["q"] = jump
            st.session_state["show_ans"] = False
            st.rerun()


# -------------------------------------------------------------- Admin ---


def stage_admin() -> None:
    st.header("Admin · diagnostics")
    st.caption("Token accounting and cost. Student views stay clean.")
    pricing = config.PRICING
    c1, c2 = st.columns([1, 2])
    with c1:
        currency = st.radio("Currency", ["USD ($)", "INR (\u20b9)"], horizontal=True,
                            key="cur")
    rate = 1.0
    if currency.startswith("INR"):
        with c2:
            rate = st.number_input("USD \u2192 INR rate", min_value=1.0, value=83.0,
                                   step=0.5, key="fx")
    sym = "\u20b9" if currency.startswith("INR") else "$"

    from run_pipeline import summarize_tokens

    rows, totals = [], {"turns": 0, "in": 0, "fresh": 0, "cached": 0,
                        "out": 0, "rsn": 0, "cost": 0.0}
    for r in _all_papers():
        s = summarize_tokens(r["id"])
        t = s["total"]
        if not t["turns"]:
            continue
        totals["turns"] += t["turns"]
        totals["in"] += t["input"]
        totals["fresh"] += t["fresh_input"]
        totals["cached"] += t["cache_read"]
        totals["out"] += t["output"]
        totals["rsn"] += t["reasoning"]
        totals["cost"] += s["cost_usd"]
        rows.append({
            "paper": f"#{r['id']} {display_name(r)[:40]}",
            "status": r["status"] or "uploaded",
            "turns": t["turns"],
            "input": t["input"],
            "fresh": t["fresh_input"],
            "cached": t["cache_read"],
            "output": t["output"],
            "reasoning": t["reasoning"],
            "wall": (f"{r['elapsed_sec']:.0f}s" if r["elapsed_sec"] else "\u2014"),
            "cost": round(s["cost_usd"] * rate, 4),
        })
    if not rows:
        st.info("No token usage recorded yet \u2014 run a pipeline first.")
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total cost", f"{sym}{totals['cost'] * rate:,.2f}")
    m2.metric("Fresh input (billed)", f"{totals['fresh']:,}")
    m3.metric("Cache read", f"{totals['cached']:,}")
    m4.metric("Turns", f"{totals['turns']:,}")
    st.caption(
        f"Pricing $/Mtok \u2014 in: {pricing['input_per_mtok']}, "
        f"cached: {pricing['cache_read_per_mtok']}, out: {pricing['output_per_mtok']}"
        + (f" \u00b7 1 USD = \u20b9{rate:g}" if currency.startswith("INR") else "")
    )
    cost_label = "cost (\u20b9)" if currency.startswith("INR") else "cost ($)"
    st.dataframe(rows, width="stretch", hide_index=True,
                 column_order=["paper", "status", "turns", "input", "fresh",
                               "cached", "output", "reasoning", "wall", "cost"],
                 column_config={"cost": st.column_config.NumberColumn(cost_label)})
    for r in _all_papers():
        if r["error"]:
            st.warning(f"#{r['id']}: {r['error']}")
    st.divider()
    with st.expander("Danger zone: delete a paper"):
        st.caption("Removes the DB row, its questions + token rows, and its Outputs folder. "
                   "Source PDFs in uploads/ are kept — re-register to bring it back.")
        all_p = _all_papers()
        if all_p:
            victim = st.selectbox(
                "Paper to delete",
                [f"#{r['id']} · {display_name(r)} [{r['status'] or 'uploaded'}]" for r in all_p],
                key="del_paper")
            vid = int(victim.split()[0][1:])
            confirm = st.checkbox(f"I understand #{vid} and its outputs will be deleted",
                                  key="del_confirm")
            if st.button("Delete paper", type="primary", disabled=not confirm,
                         key="del_go"):
                import shutil

                database.delete_paper(vid)
                out = directory_manager.paper_dir(vid)
                if out.is_dir():
                    shutil.rmtree(out)
                st.success(f"Deleted paper {vid}.")
                st.rerun()


STAGES = {
    "01 · Upload & verify": stage_upload,
    "02 · Processing": stage_processing,
    "03 · Paper library": stage_library,
    "Admin": stage_admin,
}
STAGES[stage]()
