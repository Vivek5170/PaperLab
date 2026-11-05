"""PaperLab: public library view + password-gated admin area."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import time

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import config  # noqa: F401  (pins env first)
import database
import directory_manager
from app.auth import SESSION_KEY, check_password, uses_default_password
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

st.set_page_config(page_title="PaperLab · Physics extraction", page_icon="⚛️", layout="wide")
database.init_db()

st.markdown(
    """
    <style>
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div {
        padding-left: 0 !important;
        padding-right: 0 !important;
    }
    [data-testid="stSidebar"] .stButton {
        margin-left: 0 !important;
        margin-right: 0 !important;
    }
    [data-testid="stSidebar"] .stButton > button {
        font-size: 1.12rem !important;
        font-weight: 700 !important;
        padding: 0.6rem 0.75rem !important;
        border-radius: 0 !important;
        border-left: none !important;
        border-right: none !important;
    }
    [data-testid="stSidebar"] .stMarkdown p,
    [data-testid="stSidebar"] .stCaption {
        padding-left: 1rem;
        padding-right: 1rem;
    }
    [data-testid="stSidebar"] hr {
        margin-left: 1rem !important;
        margin-right: 1rem !important;
    }
    [data-testid="stSidebar"] .stCaption {
        font-size: 0.92rem !important;
    }
    .side-brand {
        font-size: 1.45rem !important;
        font-weight: 800 !important;
        margin-bottom: 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Offline discipline: non-done papers whose source PDFs were deleted from
# data/uploads or data/processing are hard-deleted (DB row + Outputs; done
# papers are exempt). Runs on every script rerun; a no-op when all present.
_swept = reconcile_missing_sources()
if _swept:
    st.toast(f"Removed papers with missing source files: {sorted(_swept)}")


def is_admin() -> bool:
    """Session flag only: a refresh or new tab starts logged out."""
    return bool(st.session_state.get(SESSION_KEY))


@st.dialog("Admin login")
def _login_dialog() -> None:
    pw = st.text_input("Password", type="password", key="pw_login")
    if st.button("Unlock", key="pw_go", type="primary"):
        if check_password(pw):
            st.session_state[SESSION_KEY] = True
            st.session_state.pop("pw_login", None)
            st.toast("Admin mode on.")
            st.rerun()
        else:
            st.error("Wrong password.")


def _topbar() -> None:
    """Slim utility bar: breadcrumb left, admin toggle right."""
    h1, h2 = st.columns([5, 1])
    with h1:
        st.caption(f"📍 {st.session_state.get('page', '📖 Library')}")
    with h2:
        if is_admin():
            if st.button("🔓 Admin · Logout", key="admin_off"):
                st.session_state.pop(SESSION_KEY, None)
                st.session_state["page"] = "📖 Library"
                st.toast("Admin mode off.")
                st.rerun()
        else:
            if st.button("🔒 Admin", key="admin_on"):
                _login_dialog()


def _all_papers():
    conn = database.get_connection()
    try:
        return conn.execute("SELECT * FROM papers ORDER BY id DESC").fetchall()
    finally:
        conn.close()


def _qn_sort_key(qn: str):
    """Order questions: optional SEC- prefix, then numeric, then the rest.

    Bare ids ("15a"->("",15,"a"), "31-32_paragraph"->("",31,...)) keep their
    old order; namespaced ids ("A-01"->("A",1,""), "B-31-32_paragraph") sort
    by section first. Zero-padded numbers (see extractor prompt) required.
    """
    m = re.match(r"^(?:([A-Za-z]+)-)?(\d+)(.*)$", qn or "")
    if not m:
        return (1, qn or "", 0, "")
    sec, num, rest = m.groups()
    return (0, sec or "", int(num), rest or "")


def _paper_questions(pid: int):
    conn = database.get_connection()
    try:
        # Numeric question order (insertion id breaks after targeted reruns:
        # re-extracted questions would sort last). Sorted in Python so
        # section-prefixed ids ("A-01", "B-01") order correctly; SQLite CAST
        # would map every prefixed id to 0 and scramble sections.
        rows = conn.execute(
            "SELECT question_number, qtype FROM questions WHERE paper_id = ?",
            (pid,)).fetchall()
        return sorted(rows, key=lambda r: _qn_sort_key(r["question_number"]))
    finally:
        conn.close()


_topbar()

with st.sidebar:
    st.markdown('<p class="side-brand">PaperLab</p>', unsafe_allow_html=True)
    st.caption("Physics extraction console · JEE / NEET archive")
    st.divider()
    st.caption("🧭 Navigate")
    _nav_choice = st.session_state.setdefault("page", "📖 Library")
    if st.button("📖  Library", key="nav_lib", width="stretch",
                 type="primary" if _nav_choice == "📖 Library" else "secondary"):
        st.session_state["page"] = "📖 Library"
        st.rerun()
    if st.button("🏷️  Needs topics", key="nav_nt", width="stretch",
                 type="primary" if _nav_choice == "🏷️ Needs topics" else "secondary"):
        st.session_state["page"] = "🏷️ Needs topics"
        st.rerun()
    if st.button("🌳  Topic tree", key="nav_tree", width="stretch",
                 type="primary" if _nav_choice == "🌳 Topic tree" else "secondary"):
        st.session_state["page"] = "🌳 Topic tree"
        st.rerun()
    _adm_label = "🛠  Admin" + ("  🔓" if is_admin() else "")
    if st.button(_adm_label, key="nav_admin", width="stretch",
                 type="primary" if _nav_choice == "🛠 Admin" else "secondary"):
        st.session_state["page"] = "🛠 Admin"
        st.rerun()
    st.divider()
    _rows = _all_papers()
    _b = bucket_papers(_rows)
    _lock = "🔓 admin" if is_admin() else "🔒 locked"
    st.caption(f"✅ {len(_b['done'])} done · ⏳ {len(_b['queued'])} queued")
    st.caption(f"⚙️ {len(_b['running'])} running · "
               f"❌ {len(_b['failed'])} failed · {_lock}")
page = st.session_state.get("page", "📖 Library")


# ------------------------------------------------- figures & tex ---


def _figure_mode(path: str) -> str | None:
    """Provenance tag from figures/_modes.json (None when never recorded)."""
    import json

    try:
        sidecar = Path(path).parent / "_modes.json"
        if sidecar.is_file():
            return json.loads(sidecar.read_text(encoding="utf-8")).get(Path(path).name)
    except Exception:
        pass
    return None


_MODE_STYLE = {
    "snap": ("green", "snap — original PNG bytes"),
    "vector": ("blue", "vector — assisted crop"),
    "plain": ("orange", "plain — page crop"),
    "exact": ("violet", "exact — hand-drawn box"),
    "manual": ("gray", "manual — uploaded/edited"),
}


def _show_figure(path: str) -> None:
    """Show a figure capped so plain (200dpi) crops don't dominate.

    Snapped originals are tiny (their native pixels) while plain crops are
    full render-scale; without a cap the same diagram shows at 265px in one
    question and 700px in the next. 400px matches the compiled view's
    0.65\\linewidth cap feel and stays readable.
    """
    from PIL import Image

    try:
        w = Image.open(path).size[0]
    except Exception:
        w = 400
    mode = _figure_mode(path)
    if mode in _MODE_STYLE:
        color, label = _MODE_STYLE[mode]
        st.markdown(f":{color}[● {label}]")
    st.image(path, caption=Path(path).name, width=min(w, 400))


def _show_match_table(table: dict, key: str) -> None:
    """Render a List-I/List-II table with figures inline in their cells.

    Markdown tables cannot hold images in this pipeline (figures are split
    into st.image segments), so the table is laid out with columns: figure
    columns get double weight, text columns single.
    """
    ncols = max([len(table["header"])] +
                [len(r) for r in table["rows"]]) if table["rows"] else 0
    if not ncols:
        return

    def _has_fig(col: int) -> bool:
        if col < len(table["header"]) and any(
                k == "fig" for k, _ in table["header"][col]):
            return True
        return any(col < len(r) and any(k == "fig" for k, _ in r[col])
                   for r in table["rows"])

    weights = [2 if _has_fig(c) else 1 for c in range(ncols)]

    def _row(cells: list, tag: str, bold: bool = False) -> None:
        cols = st.columns(weights)
        for c, col in zip(cells, cols):
            with col:
                for kind, val in c:
                    if kind == "fig":
                        if val:
                            _show_figure(val)
                        else:
                            st.warning("Figure missing.")
                    elif val:
                        st.markdown(f"**{val}**" if bold else val)

    _row(table["header"] + [[("text", "")]] * (ncols - len(table["header"])),
         f"{key}_h", bold=True)
    st.divider()
    for i, r in enumerate(table["rows"]):
        _row(r + [[("text", "")]] * (ncols - len(r)), f"{key}_{i}")


def _render_tex_block(tex: str, base_dir: Path, key: str, label: str,
                      allow_render: bool = True) -> None:
    for kind, payload in split_tex(tex, base_dir):
        if kind == "fig":
            if payload:
                _show_figure(payload)
            else:
                st.warning("Referenced figure file is missing on disk.")
        elif kind == "table":
            _show_match_table(payload, key)
        elif kind == "display":
            st.latex(payload)
        elif payload:
            st.markdown(payload)
    if allow_render and tex_engine_available():
        if st.button(f"Render {label} as image", key=f"tex_{key}"):
            out = render_tex_to_png(tex, base_dir, f"_{label}.png")
            if out is not None:
                st.image(str(out), caption=f"{label} (compiled TeX)")
            else:
                st.error("TeX compile failed here; the view above stands.")
                try:
                    log = Path(base_dir) / f"_{label}.png.err"
                    if log.is_file():
                        with st.expander("Show compile log"):
                            st.code(log.read_text(encoding="utf-8"))
                except OSError:
                    pass


# ------------------------------------------------- 01 Upload & verify ---


def stage_upload() -> None:
    st.header("📥 Upload & verify")
    st.caption("Nothing enters processing until you explicitly confirm the pairs.")
    if "_staged_msg" in st.session_state:
        st.success(st.session_state.pop("_staged_msg"))
    q_files = st.file_uploader("Questions (or combined Q + Key + Solutions PDFs)",
                               type="pdf", accept_multiple_files=True, key="up_q")
    st.caption("Single file holding QP + Key + Solutions? Upload it here — "
               "you'll pair it with “↩ Same file (combined)” below.")
    s_files = st.file_uploader("Solution PDFs (separate files only)", type="pdf",
                               accept_multiple_files=True, key="up_s")
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
    st.caption("Solution choices per question file: a separate solution PDF, "
               "“↩ Same file (combined)” when one PDF holds QP + Key + Solutions, "
               "or “— none —” for questions-only papers.")
    if "_register_msgs" in st.session_state:
        for kind, text in st.session_state.pop("_register_msgs"):
            (st.info if kind == "info" else st.success)(text)
    pairs = auto_pair(q_names, s_names)
    final = []
    SAME = "↩ Same file (combined Q+Key+Sol)"
    for q, s_default in pairs:
        c1, c2 = st.columns([1, 1])
        c1.write(f"**{q}**")
        options = ["— none —", SAME] + s_names
        idx = options.index(s_default) if s_default in options else 0
        s_choice = c2.selectbox("Solution PDF", options, index=idx, key=f"pair_{q}")
        if s_choice == "— none —":
            final.append((q, None))
        elif s_choice == SAME:
            final.append((q, q))  # combined: same file is its own solution
        else:
            final.append((q, s_choice))

    if st.button("Confirm pairs & register", type="primary"):
        msgs = []
        for q, s in final:
            pid, reused = register_pair(str(UPLOAD_DIR / q),
                                        str(UPLOAD_DIR / s) if s else None)
            if reused:
                msgs.append(("info",
                             f"#{pid} {q}: already registered — identified, not re-queued."))
            else:
                tag = " (combined)" if s == q else (f" + {s}" if s else "")
                msgs.append(("success", f"Confirmed paper_id={pid}: {q}{tag}"))
        st.session_state["_register_msgs"] = msgs
        st.rerun()


# ------------------------------------------------------- 02 Processing ---


def stage_processing() -> None:
    st.header("⚙️ Processing")
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


def _paper_items(pid: int) -> list[tuple[str, str, str, str | None]]:
    """[(qn, question_tex, solution_tex, figures_dir|None)] in display order."""

    def _read(p):
        try:
            return p.read_text(encoding="utf-8") if p.is_file() else ""
        except OSError:
            return ""

    items = []
    for r in _paper_questions(pid):
        qn = r["question_number"]
        qdir = directory_manager.get_question_dir(pid, qn)
        figdir = qdir / "figures"
        items.append((
            qn,
            _read(qdir / "question.tex"),
            _read(qdir / "solution.tex"),
            str(figdir) if figdir.is_dir() else None,
        ))
    return items


@st.cache_data(show_spinner=False)
def _paper_pdf_cached(title: str, sig: str, items: tuple) -> bytes | None:
    """Compile the full paper PDF; cached -- sig covers sources + builder."""
    from pathlib import Path

    from app.render import _FULLPDF_REV, build_paper_pdf

    assert sig.startswith(_FULLPDF_REV + "|"), "caller must mix builder rev into sig"
    return build_paper_pdf(
        [(q, qt, st, Path(f) if f else None) for q, qt, st, f in items], title)


def _paper_pdf_button(slot, pid: int, paper_name: str) -> None:
    """Full paper PDF, built LAZILY: one click builds (cached), then downloads.

    Previously every library card read all its tex files + hashed them on
    every rerun; now nothing touches disk until the user asks for the PDF.
    """
    import hashlib

    from app.render import _FULLPDF_REV, tex_engine_available

    if not tex_engine_available():
        return
    flag = f"pdf_ready_{pid}"
    if slot.button("📄 Full PDF", key=f"mkpdf_{pid}"):
        st.session_state[flag] = True
    if not st.session_state.get(flag):
        return
    items = _paper_items(pid)
    if not items:
        slot.caption("PDF failed")
        return
    sig = _FULLPDF_REV + "|" + hashlib.sha256("\n".join(
        f"{q}\n{qt}\n{st}" for q, qt, st, _ in items).encode()).hexdigest()
    with st.spinner("Building paper PDF..."):
        pdf = _paper_pdf_cached(
            paper_name or f"Paper {pid}", sig, tuple(items))
    if pdf:
        slot.download_button("⬇ Full PDF", data=pdf,
                             file_name=f"paper{pid}_full.pdf",
                             mime="application/pdf", key=f"dl_full_{pid}")
    else:
        slot.caption("PDF failed")


@st.cache_data(show_spinner=False)
def _orig_pdf_bytes(path: str, mtime_ns: int) -> bytes | None:
    """Original-PDF bytes, cached by path+mtime so reruns never re-read."""
    try:
        p = Path(path)
        if p.is_file():
            return p.read_bytes()
    except OSError:
        return None
    return None


def _pdf_download_button(slot, path: str, key: str) -> None:
    """Original-PDF download button; quiet note when the file is gone."""
    data = None
    try:
        if path and Path(path).is_file():
            data = _orig_pdf_bytes(path, Path(path).stat().st_mtime_ns)
    except OSError:
        data = None
    if data is None:
        slot.caption("missing")
    else:
        slot.download_button("⬇", data=data, file_name=Path(path).name,
                             mime="application/pdf", key=key)


def _question_counts() -> dict:
    """Question totals per paper in ONE query (no per-card connection)."""
    conn = database.get_connection()
    try:
        return {pid: n for pid, n in
                conn.execute("SELECT paper_id, COUNT(*) FROM questions "
                             "GROUP BY paper_id").fetchall()}
    finally:
        conn.close()


def _qtype_counts() -> dict:
    """{paper_id: {qtype: n}} in ONE query for the library cards."""
    out: dict = {}
    conn = database.get_connection()
    try:
        for pid, qt, n in conn.execute(
                "SELECT paper_id, qtype, COUNT(*) FROM questions "
                "GROUP BY paper_id, qtype").fetchall():
            out.setdefault(pid, {})[qt or "unknown"] = n
    finally:
        conn.close()
    return out


def _qtype_summary(counts: dict) -> str:
    """Stable-order 'scq 4 · msq 3 ...' line; empty when no questions."""
    order = [t for t in database.QTYPE_VALUES if t in counts]
    order += [t for t in counts if t not in order]
    return " · ".join(f"{t} {counts[t]}" for t in order)


def stage_library() -> None:
    if st.session_state.get("paper") is not None:
        _paper_page()
        return
    h1, h2 = st.columns([5, 1])
    with h1:
        st.header("📖 Paper library")
    with h2:
        st.write("")
        if st.button("Refresh", key="lib_refresh"):
            st.rerun()
    all_rows = _all_papers()
    counts = _question_counts()
    qtypes = _qtype_counts()
    papers = [r for r in all_rows if (r["status"] or "") == "done"]
    show_all = st.checkbox("Include unfinished papers", value=False)
    if show_all:
        papers = all_rows
    query = st.text_input("Search papers", placeholder="fuzzy search by name…")
    exams = ["All"] + exam_options(all_rows)
    exam = st.selectbox("Exam", exams)
    papers = filter_papers(papers, query, exam)
    if not papers:
        st.info("No completed papers yet — process some on the Processing page.")
        return
    for r in papers:
        nq = counts.get(r["id"], 0)
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"### {r['paper_name'] or f'Paper {r['id']}'}")
            c1.caption(f"{r['exam_type'] or 'Unknown exam'} · "
                       f"{r['paper_date'] or 'undated'} · "
                       f"{nq} questions · #{r['id']}")
            if qtypes.get(r["id"]):
                c1.caption(f"🏷️ {_qtype_summary(qtypes[r['id']])}")
            if r["source_institute"]:
                c1.caption(f"🏫 {r['source_institute']}")
            if r["question_pdf_path"]:
                q1, q2 = c1.columns([11, 1])
                q1.caption(f"📄 {r['question_pdf_path']}")
                _pdf_download_button(q2, r["question_pdf_path"], f"dl_q_{r['id']}")
            if r["solution_pdf_path"]:
                s1, s2 = c1.columns([11, 1])
                s1.caption(f"📝 {r['solution_pdf_path']}")
                _pdf_download_button(s2, r["solution_pdf_path"], f"dl_s_{r['id']}")
            if c2.button("Open", key=f"lib_{r['id']}", width="stretch"):
                st.session_state["paper"] = r["id"]
                st.session_state["q"] = None
                st.session_state["show_ans"] = False
                st.rerun()  # stop here: the fresh run renders the sub-page
            _paper_pdf_button(c2, r["id"], r["paper_name"])
    _reader()


def _paper_page() -> None:
    """Focused sub-page for one opened paper, with a way back."""
    if st.button("← Back to library", key="back_lib"):
        for k in ("paper", "q", "show_ans"):
            st.session_state.pop(k, None)
        st.rerun()
    _reader()


def _classification_form(pid: int, qn: str, cur_qt: str) -> None:
    """Per-question Edit panel: type, difficulty, topics, suggestion.

    Available without admin mode; figure management stays admin-gated.
    One Save writes everything through the validated database helpers.
    """
    try:
        qid = database.get_question_id(pid, qn)
    except ValueError as exc:
        st.error(str(exc))
        return
    conn = database.get_connection()
    try:
        qrow = conn.execute(
            "SELECT difficulty, topic_suggestion FROM questions WHERE id = ?",
            (qid,)).fetchone()
    finally:
        conn.close()
    cur_diff = qrow["difficulty"] if qrow else None
    cur_sugg = qrow["topic_suggestion"] or "" if qrow else ""
    cur_links = [c for c, _, _ in database.get_question_links(qid)]
    options = database.topic_options()
    path_of = {code: path for code, path, _ in options}

    with st.form(key=f"cls_{pid}_{qn}"):
        st.caption("First topic = primary.")
        qt_opts = list(database.QTYPE_VALUES)
        new_qt = st.selectbox(
            "Question type", qt_opts,
            index=qt_opts.index(cur_qt) if cur_qt in qt_opts else len(qt_opts) - 1)
        diff_opts = ["Not graded", *database.DIFFICULTY_VALUES]
        new_diff = st.selectbox(
            "Difficulty", diff_opts,
            index=diff_opts.index(cur_diff) if cur_diff in diff_opts else 0)
        new_codes = st.multiselect(
            "Topics (search by path)", [c for c, _, _ in options],
            default=[c for c in cur_links if c in path_of],
            format_func=lambda c: path_of.get(c, c))
        new_sugg = st.text_area(
            "Suggestion (why nothing fit / proposed new topic)", value=cur_sugg)
        if st.form_submit_button("Save"):
            try:
                if new_qt != cur_qt:
                    database.set_question_qtype(pid, qn, new_qt)
                database.set_question_difficulty(
                    pid, qn,
                    None if new_diff == "Not graded" else new_diff,
                    topic_suggestion=new_sugg.strip())
                if new_codes != cur_links:
                    database.set_question_topics(qid, new_codes, src="human")
                st.toast(f"Saved {qn}")
            except ValueError as exc:
                st.error(str(exc))
            st.rerun()


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
    import json as _json

    try:
        _secs = _json.loads(paper["sections"]) if paper["sections"] else []
    except (ValueError, TypeError):
        _secs = []
    _sec_of: dict = {}
    for _s in _secs:
        for _qn0 in _s.get("questions", []):
            _sec_of[_qn0] = (_s.get("section", ""), _s.get("basis", ""))
    _rows = _paper_questions(pid)
    _qt_of = {r["question_number"]: (r["qtype"] or "unknown") for r in _rows}
    ids = question_ids(_rows)
    if not ids:
        st.info("No questions submitted for this paper yet.")
        return
    if st.session_state.get("q") not in ids:
        st.session_state["q"] = ids[0]
    nav, reading = st.columns([1, 3])
    with nav:
        st.caption("Questions")
        for qn in ids:
            _qt = _qt_of.get(qn, "unknown")
            if st.button(f"{qn} · {_qt}", key=f"nav_{pid}_{qn}", width="stretch"):
                st.session_state["q"] = qn
                st.session_state["show_ans"] = False
    with reading:
        qn = st.session_state["q"]
        qdir = directory_manager.get_question_dir(pid, qn)
        editable = is_admin()
        cur_qt = _qt_of.get(qn, "unknown")
        sec_name, sec_basis = _sec_of.get(qn, ("", ""))
        st.subheader(f"Question {qn}")
        st.caption(f"🏷️ {cur_qt}" + (f" · {sec_name}" if sec_name else ""))
        _mconn = database.get_connection()
        try:
            _mrow = _mconn.execute(
                "SELECT id, difficulty FROM questions"
                " WHERE paper_id = ? AND question_number = ?",
                (pid, qn)).fetchone()
        finally:
            _mconn.close()
        st.caption(f"🎯 {_mrow['difficulty']}"
                   if _mrow and _mrow["difficulty"] else "🎯 not graded")
        _links = database.get_question_links(_mrow["id"]) if _mrow else []
        if _links:
            for _i, (_code, _rank, _src) in enumerate(_links):
                try:
                    _path = database.topic_path(_code)
                except ValueError:
                    _path = _code
                st.caption(("★ " if _i == 0 else "+ ") + _path
                           + ("" if _src == "human" else " (auto)"))
        else:
            st.caption("📚 no topics yet")
        if sec_basis:
            with st.expander("Why this type (section basis)", expanded=False):
                st.caption(sec_basis)
        # Classification editing is per-question via its own Edit button:
        # no admin needed, and admin's figure powers are not involved.
        edit_key = f"edit_{pid}_{qn}"
        editing = st.session_state.get(edit_key, False)
        if st.button("Done" if editing else "✏️ Edit classification",
                      key=f"{edit_key}_btn"):
            st.session_state[edit_key] = not editing
            st.rerun()
        if editing:
            _classification_form(pid, qn, cur_qt)
        with st.container():
            qtex = (qdir / "question.tex").read_text(encoding="utf-8") \
                if (qdir / "question.tex").is_file() else "*missing*"
            _render_tex_block(qtex, qdir, f"{pid}_{qn}_q", "question",
                              allow_render=editable)
        if st.button("Show solution" if not st.session_state.get("show_ans")
                     else "Hide solution", key=f"ans_{pid}_{qn}"):
            st.session_state["show_ans"] = not st.session_state.get("show_ans")
        if st.session_state.get("show_ans"):
            stex = (qdir / "solution.tex").read_text(encoding="utf-8") \
                if (qdir / "solution.tex").is_file() else "*missing*"
            _render_tex_block(stex, qdir, f"{pid}_{qn}_s", "solution",
                              allow_render=editable)
        if editable:
            with st.expander("Manage figures", expanded=False):
                _figure_manager(pid, qn, qdir)
        elif list_figures(qdir):
            st.caption("🔒 Figure editing needs admin mode.")
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
    st.header("🛠 Admin")
    if not is_admin():
        st.warning("This area needs admin mode — use the 🔒 Admin button at the top right.")
        if st.button("Log in", key="admin_wall_go"):
            _login_dialog()
        return
    if uses_default_password():
        st.warning('Admin password is still the default "admin" — '
                   "set PAPERLAB_ADMIN_PASSWORD in .env before hosting.")
    tab_stats, tab_flow = st.tabs(["📊 Statistics", "📥 Upload & Processing"])
    with tab_stats:
        _admin_statistics()
    with tab_flow:
        stage_upload()
        st.divider()
        stage_processing()


def _admin_statistics() -> None:
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

    rows, totals = [], {"turns": 0, "in": 0, "cached": 0,
                        "out": 0, "rsn": 0, "cost": 0.0, "tagging": 0.0}
    for r in _all_papers():
        s = summarize_tokens(r["id"])
        t = s["total"]
        if not t["turns"]:
            continue
        totals["turns"] += t["turns"]
        totals["in"] += t["input"]
        totals["cached"] += t["cache_read"]
        totals["out"] += t["output"]
        totals["rsn"] += t["reasoning"]
        totals["cost"] += s["cost_usd"]
        tp = s["per_phase"].get("topics", {})
        topics_cost_usd = (
            (tp.get("input", 0) - tp.get("cache_read", 0)) / 1e6 * pricing["input_per_mtok"]
            + tp.get("cache_read", 0) / 1e6 * pricing["cache_read_per_mtok"]
            + tp.get("output", 0) / 1e6 * pricing["output_per_mtok"]
        ) if tp else 0.0
        totals["tagging"] += topics_cost_usd
        rows.append({
            "paper": f"#{r['id']} {display_name(r)[:40]}",
            "status": r["status"] or "uploaded",
            "turns": t["turns"],
            "input": t["input"],
            "cached": t["cache_read"],
            "output": t["output"],
            "reasoning": t["reasoning"],
            "wall": (f"{r['elapsed_sec']:.0f}s" if r["elapsed_sec"] else "\u2014"),
            "extraction": round((s["cost_usd"] - topics_cost_usd) * rate, 4),
            "tagging": round(topics_cost_usd * rate, 4),
            "total": round(s["cost_usd"] * rate, 4),
        })
    if not rows:
        st.info("No token usage recorded yet \u2014 run a pipeline first.")
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total cost", f"{sym}{totals['cost'] * rate:,.2f}")
    m2.metric("Extraction", f"{sym}{(totals['cost'] - totals['tagging']) * rate:,.2f}")
    m3.metric("Tagging", f"{sym}{totals['tagging'] * rate:,.2f}")
    m4.metric("Turns", f"{totals['turns']:,}")
    st.caption(
        f"Pricing $/Mtok \u2014 in: {pricing['input_per_mtok']}, "
        f"cached: {pricing['cache_read_per_mtok']}, out: {pricing['output_per_mtok']}"
        + (f" \u00b7 1 USD = \u20b9{rate:g}" if currency.startswith("INR") else "")
    )
    cur = "(\u20b9)" if currency.startswith("INR") else "($)"
    st.dataframe(rows, width="stretch", hide_index=True,
                 column_order=["paper", "status", "turns", "input",
                               "cached", "output", "reasoning", "wall",
                               "extraction", "tagging", "total"],
                 column_config={
                     "extraction": st.column_config.NumberColumn(f"extraction {cur}"),
                     "tagging": st.column_config.NumberColumn(f"tagging {cur}"),
                     "total": st.column_config.NumberColumn(f"total {cur}")})
    with st.expander("Breakdown by phase (indexer / extractor / topics)",
                      expanded=False):
        phase_totals: dict = {}
        for r in _all_papers():
            for ph, p in summarize_tokens(r["id"])["per_phase"].items():
                s = phase_totals.setdefault(
                    ph, {"turns": 0, "in": 0, "cached": 0, "out": 0})
                s["turns"] += p["turns"]
                s["in"] += p["input"]
                s["cached"] += p["cache_read"]
                s["out"] += p["output"]
        if not phase_totals:
            st.caption("No phases recorded yet.")
        else:
            phase_rows = []
            for ph, s in sorted(phase_totals.items()):
                fresh = s["in"] - s["cached"]
                phase_rows.append({
                    "phase": ph,
                    "turns": s["turns"],
                    "fresh": fresh,
                    "cached": s["cached"],
                    "output": s["out"],
                    "cost": round((fresh / 1e6 * pricing["input_per_mtok"]
                                    + s["cached"] / 1e6 * pricing["cache_read_per_mtok"]
                                    + s["out"] / 1e6 * pricing["output_per_mtok"]) * rate, 4),
                })
            st.dataframe(phase_rows, width="stretch", hide_index=True,
                         column_order=["phase", "turns", "fresh", "cached",
                                       "output", "cost"],
                         column_config={"cost": st.column_config.NumberColumn(
                             f"cost {cur}")})
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


def _untagged_queue() -> list:
    """Questions with zero topic rows (the Needs-topics queue)."""
    conn = database.get_connection()
    try:
        return conn.execute(
            "SELECT q.paper_id, q.question_number, q.qtype, q.difficulty,"
            " q.topic_suggestion FROM questions q"
            " LEFT JOIN question_topics t ON t.question_id = q.id"
            " WHERE t.question_id IS NULL"
            " ORDER BY q.paper_id, q.id").fetchall()
    finally:
        conn.close()


def stage_needs_topics() -> None:
    st.header("🏷️ Needs topics")
    queue = _untagged_queue()
    conn = database.get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM questions").fetchone()["c"]
    finally:
        conn.close()
    st.caption(f"{total - len(queue)} of {total} questions tagged.")
    if not queue:
        st.success("Fully tagged — nothing left in the queue.")
        return
    pids = sorted({r["paper_id"] for r in queue})
    pick = st.selectbox("Paper", ["All"] + [f"#{p}" for p in pids], key="nt_paper")
    items = [r for r in queue
             if pick == "All" or r["paper_id"] == int(pick[1:])]
    if not items:
        st.info("Nothing untagged under this filter.")
        return
    idx_key = f"nt_idx_{pick}"
    idx = min(st.session_state.get(idx_key, 0), len(items) - 1)
    cur = items[idx]
    pid, qn = cur["paper_id"], cur["question_number"]
    n1, n2, n3 = st.columns([1, 3, 1])
    with n1:
        if st.button("← Prev", key=f"nt_prev_{pick}",
                      disabled=(idx == 0), width="stretch"):
            st.session_state[idx_key] = idx - 1
            st.rerun()
    with n2:
        st.subheader(f"Paper #{pid} · Question {qn}")
        st.caption(f"{idx + 1} of {len(items)} here")
    with n3:
        if st.button("Next →", key=f"nt_next_{pick}",
                      disabled=(idx == len(items) - 1), width="stretch"):
            st.session_state[idx_key] = idx + 1
            st.rerun()
    if cur["topic_suggestion"]:
        st.info(f"Agent suggestion: {cur['topic_suggestion']}")
    qdir = directory_manager.get_question_dir(pid, qn)
    with st.container():
        qtex = (qdir / "question.tex").read_text(encoding="utf-8") \
            if (qdir / "question.tex").is_file() else "*missing*"
        _render_tex_block(qtex, qdir, f"nt_{pid}_{qn}_q", "question",
                          allow_render=False)
    with st.expander("Solution (for tagging context)", expanded=False):
        stex = (qdir / "solution.tex").read_text(encoding="utf-8") \
            if (qdir / "solution.tex").is_file() else "*missing*"
        _render_tex_block(stex, qdir, f"nt_{pid}_{qn}_s", "solution",
                          allow_render=False)
    _classification_form(pid, qn, cur["qtype"] or "unknown")


def _all_topics() -> list:
    """All topic rows in seed order (413 rows, one query)."""
    conn = database.get_connection()
    try:
        return conn.execute(
            "SELECT code, parent, level, name, descr, rev FROM topics "
            "ORDER BY rowid").fetchall()
    finally:
        conn.close()


def stage_tree() -> None:
    if not is_admin():
        st.header("🌳 Topic tree")
        st.warning("This area needs admin mode — use the 🔒 Admin button at the top right.")
        return
    st.header("🌳 Topic tree")
    rows = _all_topics()
    if not rows:
        st.info("Tree is empty — seed it with database.init_topics().")
        return
    by_code = {r["code"]: r for r in rows}
    kids: dict = {}
    for r in rows:
        kids.setdefault(r["parent"], []).append(r["code"])
    def _label(code: str) -> str:
        r = by_code[code]
        n = len(kids.get(code, []))
        suffix = f" ({n})" if n and r["level"] != "subtopic" else ""
        return f"{code} · {r['name']}{suffix}"

    st.caption("Drill in and out. Only one level is shown at a time. "
               "Saves are revision-guarded: concurrent edits fail loudly.")
    query = st.text_input("Search (code, name, or description)",
                          placeholder="e.g. doppler, PH24, rolling…", key="tree_q")
    if query and query.strip():
        q = query.strip().lower()
        hits = [r["code"] for r in rows
                if q in r["code"].lower() or q in (r["name"] or "").lower()
                or q in (r["descr"] or "").lower()][:30]
        if not hits:
            st.info("No matches.")
        else:
            pick = st.selectbox("Matches", hits, format_func=_label, key="tree_hit")
            if st.button("Open", key="tree_open"):
                anc, _c = [], pick
                while _c is not None and _c in by_code:
                    anc.append(_c)
                    _c = by_code[_c]["parent"]
                st.session_state["tree_path"] = list(reversed(anc))
                st.rerun()
    mods = [r["code"] for r in rows if r["level"] == "module"]
    # Drill-down path: [] = modules, [M1] = its chapters, ...
    path = list(st.session_state.get("tree_path", []))
    _valid, _parent = [], None
    for _c in path:
        _n = by_code.get(_c)
        if _n is None or _n["parent"] != _parent:
            _valid = []
            break
        _valid.append(_c)
        _parent = _c
    path = _valid
    st.caption(" › ".join(["All modules"]
                           + [f"{c} · {by_code[c]['name']}" for c in path]))
    if path and st.button("← Back", key="tree_back"):
        st.session_state["tree_path"] = path[:-1]
        st.rerun()

    def _del_button(code: str) -> None:
        if st.button("🗑", key=f"tree_rowdel_{code}"):
            try:
                database.delete_topic(code)
                st.toast(f"Deleted {code}")
                st.session_state["tree_path"] = [
                    c for c in st.session_state.get("tree_path", [])
                    if c != code]
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    if not path:
        # ROOT: modules only, with add.
        st.subheader(f"Modules ({len(mods)})")
        for mod in mods:
            r1, r2, r3 = st.columns([10, 1, 1])
            r1.caption(f"{mod} · {by_code[mod]['name']} "
                       f"({len(kids.get(mod, []))} chapters)")
            if r2.button("Open →", key=f"tree_in_{mod}"):
                st.session_state["tree_path"] = [mod]
                st.rerun()
            with r3:
                _del_button(mod)
        a1, a2 = st.columns([9, 3])
        mn = a1.text_input("New module name", key="tree_add_mod_n",
                           placeholder="Type new module name…")
        if a2.button("＋ Add", key="tree_add_mod"):
            try:
                code = database.add_module(mn)
                st.toast(f"Added {code}")
                st.session_state["tree_path"] = [code]
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        return

    focus = path[-1]
    node = by_code[focus]
    if node is not None:
        st.divider()
        h1, h2, h3 = st.columns([9, 2, 1])
        h1.subheader(f"{node['code']} · {node['name']}")
        h1.caption(f"{node['level']} · rev {node['rev']}")
        if node["level"] == "subtopic" and node["descr"]:
            h1.caption(node["descr"])
        if h2.button("← Up", key=f"tree_up_{focus}"):
            st.session_state["tree_path"] = path[:-1]
            st.rerun()
        with h3:
            _del_button(focus)
        with st.form(key=f"tree_edit_{focus}"):
            new_name = st.text_input("Name", value=node["name"])
            # Description exists only on subtopics (agent's guide).
            new_descr = st.text_area("Description (classifying guide)",
                                     value=node["descr"] or "") \
                if node["level"] == "subtopic" else ""
            saved = st.form_submit_button("Save")
        if saved:
            try:
                new_rev = database.update_topic(
                    focus, new_name, new_descr, int(node["rev"]))
                st.toast(f"Saved {focus} (rev {new_rev})")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        # Drill-down: children as selectable rows + inline add, same
        # shape at module / chapter / week level.
        child_level = {"module": "chapter", "chapter": "week",
                       "week": "subtopic"}.get(node["level"])
        st.divider()
        if child_level is None:
            st.caption("Subtopics have no children.")
        else:
            st.subheader(f"{child_level.title()}s "
                         f"({len(kids.get(focus, []))})")
            for ch in kids.get(focus, []):
                r1, r2, r3 = st.columns([9, 2, 1])
                extra = ""
                if child_level != "subtopic":
                    extra = f" ({len(kids.get(ch, []))})"
                r1.caption(f"{ch} · {by_code[ch]['name']}{extra}")
                if r2.button("Open →", key=f"tree_drill_{focus}_{ch}"):
                    st.session_state["tree_path"] = path + [ch]
                    st.rerun()
                with r3:
                    _del_button(ch)
            a1, a2 = st.columns([9, 3])
            cn = a1.text_input(f"New {child_level} name",
                               key=f"tree_add_n_{focus}",
                               placeholder=f"Type new {child_level} name…")
            cd = st.text_area("Description (optional)",
                              key=f"tree_add_d_{focus}") \
                if child_level == "subtopic" else ""
            if a2.button(f"＋ Add", key=f"tree_add_{focus}"):
                try:
                    code = database.add_topic(focus, child_level, cn, cd)
                    st.toast(f"Added {code}")
                    st.session_state["tree_path"] = path + [code]
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        # Move this level elsewhere (codes never change, so existing
        # question tags keep working; rename is always safe too).
        st.divider()
        st.subheader("Move this level")
        if node["level"] == "subtopic":
            chap = focus.split(".")[0]
            dests = [x for x in rows
                     if x["level"] == "week" and x["code"].startswith(chap + "-")
                     and x["code"] != node["parent"]]
            dest = st.selectbox("New parent week", [d["code"] for d in dests],
                                format_func=_label, key=f"tree_mv_{focus}") \
                if dests else None
            if dest and st.button("Move", key=f"tree_mvgo_{focus}"):
                try:
                    database.move_topic(focus, dest)
                    st.toast(f"Moved to {dest}")
                    st.session_state["tree_path"] = path[:-1] + [dest, focus]
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        elif node["level"] == "chapter":
            dest = st.selectbox("New parent module", mods,
                                format_func=_label, key=f"tree_mv_{focus}")
            if st.button("Move", key=f"tree_mvgo_{focus}"):
                try:
                    database.move_topic(focus, dest)
                    st.toast(f"Moved to {dest}")
                    st.session_state["tree_path"] = [dest, focus]
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        else:
            st.caption("Weeks stay in their chapter; modules can't move.")
        _tconn = database.get_connection()
        try:
            nlinks = _tconn.execute(
                "SELECT COUNT(*) AS c FROM question_topics WHERE topic_code = ?",
                (focus,)).fetchone()["c"]
        finally:
            _tconn.close()
        st.caption(f"Used by {nlinks} question tag(s), "
                   f"{len(kids.get(focus, []))} children. "
                   "Delete is the 🗑 on its row (refused while tags "
                   "or children exist — retag/move them first).")


if page == "🛠 Admin":
    stage_admin()
elif page == "🏷️ Needs topics":
    stage_needs_topics()
elif page == "🌳 Topic tree":
    stage_tree()
else:
    stage_library()
