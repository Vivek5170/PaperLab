"""PaperLab: three-stage UI (Upload & verify / Processing / Paper library)."""

from __future__ import annotations

from pathlib import Path
import sys
import time

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import config  # noqa: F401  (pins env first)
import database
import directory_manager
from app.library import bucket_papers, display_name, exam_options, filter_papers
from app.pairing import (UPLOAD_DIR, auto_pair, delete_paper_everywhere,
                         reconcile_missing_sources, register_pair, save_uploads,
                         split_candidates)
from app.figures import (crop_image_file, figure_side, insert_figure_ref,
                         list_figures, next_figure_name, referencing_tex,
                         remove_figure_refs, save_uploaded_figure)
from app.reader import neighbor_ids, paper_title, question_ids
from app.render import render_tex_to_png, split_tex, tex_engine_available
from app.runs import get_registry, reset_stuck_running_once
from run_pipeline import run_pipeline, summarize_tokens

st.set_page_config(page_title="PaperLab", page_icon="📄", layout="wide")
database.init_db()

st.title("PaperLab")
st.caption("Question bank · Mathematics & CS")

# Offline discipline: non-done papers whose source PDFs were deleted from
# data/uploads or data/processing are hard-deleted (DB row + Outputs; done
# papers are exempt). Runs on every script rerun; a no-op when all present.
_swept = reconcile_missing_sources()
if _swept:
    st.toast(f"Removed papers with missing source files: {sorted(_swept)}")

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
    if "_staged_msg" in st.session_state:
        st.success(st.session_state.pop("_staged_msg"))
    q_files = st.file_uploader("Question PDFs", type="pdf", accept_multiple_files=True,
                               key="up_q")
    s_files = st.file_uploader("Solution PDFs", type="pdf", accept_multiple_files=True,
                               key="up_s")
    if st.button("Stage files"):
        nq = len(save_uploads(q_files or []))
        ns = len(save_uploads(s_files or []))
        st.session_state["_staged_msg"] = (
            f"Staged {nq} question + {ns} solution PDFs.")
        st.session_state.pop("up_q", None)
        st.session_state.pop("up_s", None)
        st.rerun()

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
    q_names, s_names = split_candidates([n for n in staged if n not in rm])
    st.divider()
    st.subheader("Verify pairs")
    st.caption("Auto-matched by filename — correct any mismatch before confirming.")
    if "_register_msgs" in st.session_state:
        for kind, text in st.session_state.pop("_register_msgs"):
            (st.info if kind == "info" else st.success)(text)
    pairs = auto_pair(q_names, s_names)
    final = []
    for q, s_default in pairs:
        c1, c2 = st.columns([1, 1])
        c1.write(f"**{q}**")
        options = ["— none —"] + s_names
        idx = options.index(s_default) if s_default in options else 0
        s_choice = c2.selectbox("Solution PDF", options, index=idx, key=f"pair_{q}")
        final.append((q, None if s_choice == "— none —" else s_choice))

    if st.button("Confirm pairs & register", type="primary"):
        msgs = []
        for q, s in final:
            pid, reused = register_pair(str(UPLOAD_DIR / q),
                                        str(UPLOAD_DIR / s) if s else None)
            if reused:
                msgs.append(("info",
                             f"#{pid} {q}: already registered — identified, not re-queued."))
            else:
                msgs.append(("success",
                              f"Confirmed paper_id={pid}: {q}" + (f" + {s}" if s else "")))
        st.session_state["_register_msgs"] = msgs
        st.rerun()


# ------------------------------------------------------- 02 Processing ---


def stage_processing() -> None:
    st.header("02 · Processing")
    st.caption("Only confirmed pairs. Done papers never re-enter except by explicit rerun. "
               "Runs execute in the background; this page refreshes live.")
    stuck = reset_stuck_running_once()
    if stuck:
        st.warning(f"Marked interrupted by restart as failed (re-run to resume): "
                   f"{sorted(stuck)}")
    buckets = bucket_papers(_all_papers())

    reg = get_registry()
    live = reg.running()
    finished = reg.completed()
    if live or finished:
        st.subheader("Background jobs")
        for key in live:
            label = f"paper #{key}" if isinstance(key, int) else "sequential batch"
            st.write(f"⏳ {label} running…")
        for pid, status, info in sorted(finished, key=repr):
            detail = f"{info:.1f}s" if isinstance(info, (int, float)) else str(info)
            label = f"paper #{pid}" if isinstance(pid, int) else "batch"
            if status == "error":
                st.error(f"{label}: {info}")
            else:
                st.write(f"{label}: {status} ({detail})")
        if finished and st.button("Clear finished", key="clear_runs"):
            reg.clear_finished()
            st.rerun()

    if buckets["running"]:
        st.subheader("Running")
        for r in buckets["running"]:
            st.write(f"#{r['id']} · {display_name(r)} · `{r['status']}` …")
        if st.button("Refresh"):
            st.rerun()
        st.caption("Auto-refreshing while papers are processing…")
        time.sleep(5)
        st.rerun()
    st.subheader("Queue")
    queue = buckets["queued"] + buckets["failed"]
    if not queue:
        st.info("Queue is empty — confirm pairs on the Upload page.")
    else:
        for r in queue:
            extra = f" — {r['error']}" if r["status"] == "failed" else ""
            busy = (r["status"] or "") in ("indexing", "extracting")
            c1, c2 = st.columns([5, 1])
            with c1:
                st.write(f"#{r['id']} · {display_name(r)} · `{r['status']}`{extra}")
            with c2:
                if st.button("Delete", key=f"del_q_{r['id']}", disabled=busy):
                    delete_paper_everywhere(int(r["id"]))
                    st.rerun()

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

    def _run_sequential(pids: list[int]):
        return [_run(pid) for pid in pids]

    if st.button("Run", type="primary", disabled=not ids):
        reg = get_registry()
        started = []
        if mode.startswith("One"):
            if reg.submit(("batch", tuple(ids)), _run_sequential, ids):
                started.append(f"batch of {len(ids)}")
        else:
            for pid in ids:
                if reg.submit(pid, _run, pid):
                    started.append(f"#{pid}")
        if started:
            st.toast(f"Started in background: {', '.join(started)}")
        else:
            st.toast("Already running — see Background jobs.")
        st.rerun()
    with st.expander("History (completed)"):
        for r in bucket_papers(_all_papers())["done"]:
            st.write(f"#{r['id']} · {display_name(r)} · done")


# ----------------------------------------------------------- 03 Library ---


def stage_library() -> None:
    h1, h2 = st.columns([5, 1])
    with h1:
        st.header("03 · Paper library")
    with h2:
        st.write("")
        if st.button("Refresh", key="lib_refresh"):
            st.rerun()
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
        with st.expander("Manage figures", expanded=False):
            _figure_manager(pid, qn, qdir)
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


def _figure_manager(pid: int, qn: str, qdir) -> None:
    """File-level figure ops: re-crop existing, attach uploads, delete."""
    from PIL import Image

    from tools_extractor import verify_latex_syntax

    for fig in list_figures(qdir):
        refs = referencing_tex(qdir, fig.name)
        side = figure_side(fig.name)
        c1, c2, c3, c4 = st.columns([1, 2, 1, 1])
        c1.image(str(fig), width=120)
        c2.write(f"**{fig.name}**")
        c2.caption(f"{side} · used in: {', '.join(refs) or 'nothing'}")
        rckey = f"rcopen_{pid}_{qn}_{fig.name}"
        if c3.button("Re-crop", key=f"rc_{pid}_{qn}_{fig.name}"):
            st.session_state[rckey] = True
            st.rerun()
        arm = f"delarm_{pid}_{qn}_{fig.name}"
        if c4.button("Confirm delete" if st.session_state.get(arm) else "Delete",
                     key=f"del_{pid}_{qn}_{fig.name}"):
            if st.session_state.pop(arm, None):
                ok = True
                for which in referencing_tex(qdir, fig.name):
                    p = qdir / ("question.tex" if which == "question"
                                 else "solution.tex")
                    new, _ = remove_figure_refs(
                        p.read_text(encoding="utf-8"), fig.name)
                    v = verify_latex_syntax.invoke({"latex_string": new})
                    if v != "Valid":
                        st.error(f"Cannot delete: {which}.tex would break: {v}")
                        ok = False
                        break
                    p.write_text(new, encoding="utf-8")
                if ok:
                    fig.unlink()
                    st.success(f"Deleted {fig.name}.")
                    st.rerun()
            else:
                st.session_state[arm] = True
                st.rerun()
        if st.session_state.get(rckey):
            st.caption("Crop within the current image (cannot grow beyond it; "
                       "to expand, re-crop from the PDF via the agent).")
            l = st.slider("Left %", 0, 99, 0, key=f"cL_{pid}_{qn}_{fig.name}")
            r = st.slider("Right %", 1, 100, 100, key=f"cR_{pid}_{qn}_{fig.name}")
            t = st.slider("Top %", 0, 99, 0, key=f"cT_{pid}_{qn}_{fig.name}")
            b = st.slider("Bottom %", 1, 100, 100, key=f"cB_{pid}_{qn}_{fig.name}")
            img = Image.open(fig).convert("RGB")
            w, h = img.size
            pv = img.crop((int(l / 100 * w), int(t / 100 * h),
                           max(int(r / 100 * w), int(l / 100 * w) + 1),
                           max(int(b / 100 * h), int(t / 100 * h) + 1)))
            st.image(pv, caption="Preview", width=300)
            s1, s2 = st.columns(2)
            if s1.button("Save crop", key=f"rcsave_{pid}_{qn}_{fig.name}"):
                try:
                    crop_image_file(fig, (l / 100, t / 100, r / 100, b / 100))
                    for k in (rckey, f"cL_{pid}_{qn}_{fig.name}",
                              f"cR_{pid}_{qn}_{fig.name}",
                              f"cT_{pid}_{qn}_{fig.name}",
                              f"cB_{pid}_{qn}_{fig.name}"):
                        st.session_state.pop(k, None)
                    st.success(f"Saved {fig.name}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if s2.button("Cancel", key=f"rccancel_{pid}_{qn}_{fig.name}"):
                for k in (rckey, f"cL_{pid}_{qn}_{fig.name}",
                          f"cR_{pid}_{qn}_{fig.name}",
                          f"cT_{pid}_{qn}_{fig.name}",
                          f"cB_{pid}_{qn}_{fig.name}"):
                    st.session_state.pop(k, None)
                st.rerun()
    st.divider()
    st.caption("Add an already-cropped image")
    target = st.radio("Attach to", ["question", "solution"], horizontal=True,
                      key=f"tgt_{pid}_{qn}")
    side = "question" if target == "question" else "solution"
    nmkey = f"nm_{pid}_{qn}"
    name = st.text_input("Filename", value=next_figure_name(qdir, side), key=nmkey)
    up = st.file_uploader("Cropped image (PNG/JPG)", type=["png", "jpg", "jpeg"],
                          key=f"up_{pid}_{qn}")
    if st.button("Add figure", key=f"add_{pid}_{qn}", disabled=up is None):
        try:
            dest = save_uploaded_figure(qdir, name.strip(), bytes(up.getbuffer()))
            texp = qdir / ("question.tex" if target == "question" else "solution.tex")
            new = insert_figure_ref(texp.read_text(encoding="utf-8"), dest.name)
            v = verify_latex_syntax.invoke({"latex_string": new})
            if v != "Valid":
                dest.unlink()  # roll back: don't strand the file
                st.error(f"Not attached: {v}")
            else:
                texp.write_text(new, encoding="utf-8")
                st.session_state.pop(nmkey, None)
                st.success(f"Attached {dest.name} to {target}.")
                st.rerun()
        except ValueError as exc:
            st.error(str(exc))


# -------------------------------------------------------------- Admin ---

def stage_admin() -> None:
    st.header("Admin · diagnostics")
    st.caption("Token accounting and cost. Student views stay clean.")
    if st.button("Refresh metrics", key="admin_refresh"):
        st.rerun()
    pricing = config.PRICING
    c1, c2 = st.columns([1, 2])
    cur_options = ["USD ($)", "INR (₹)"]
    cur_index = 1 if config.CURRENCY_DEFAULT.strip().lower().startswith("in") else 0
    with c1:
        currency = st.radio("Currency", cur_options, horizontal=True,
                            key="cur", index=cur_index)
    rate = 1.0
    if currency.startswith("INR"):
        with c2:
            rate = st.number_input("USD → INR rate", min_value=1.0,
                                    value=float(config.USD_TO_INR),
                                    step=0.5, key="fx")
    sym = "\u20b9" if currency.startswith("INR") else "$"

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
        st.caption("Removes the DB row, its questions + token rows, its Outputs folder, "
                   "and its managed source PDFs (data tree). Files outside data/ "
                   "are never touched.")
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
                delete_paper_everywhere(vid)
                st.success(f"Deleted paper {vid}.")
                st.rerun()


STAGES = {
    "01 · Upload & verify": stage_upload,
    "02 · Processing": stage_processing,
    "03 · Paper library": stage_library,
    "Admin": stage_admin,
}
STAGES[stage]()
