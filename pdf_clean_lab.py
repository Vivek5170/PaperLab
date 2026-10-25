"""Throwaway lab: test clean_pdf_canvas with input/output side by side.

Run: streamlit run pdf_clean_lab.py --server.port 8503
"""

import tempfile
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from PIL import Image

from pdf_clean import (
    _chrome_images,
    _gray_patterns,
    _page_backgrounds,
    clean_pdf_canvas,
)

ARCHIVE = Path(__file__).parent / "data" / "archive"


def render_page(pdf_bytes: bytes, pageno: int, dpi: int = 110) -> Image.Image:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc[pageno - 1].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


st.set_page_config(layout="wide", page_title="PDF clean lab")
st.title("PDF clean lab — input vs output")

pdfs = sorted(ARCHIVE.glob("*.pdf"))
src = st.selectbox("Input PDF", pdfs, format_func=lambda p: p.name)
uploaded = st.file_uploader("…or upload one", type=["pdf"])

data = uploaded.read() if uploaded else (src.read_bytes() if src else None)
if not data:
    st.stop()

n_pages = fitz.open(stream=data, filetype="pdf").__len__()
col_a, col_b, col_c = st.columns(3)
with col_a:
    page = st.number_input("Page", 1, n_pages, 1)
with col_b:
    wm = st.text_input("Watermark text", "")
with col_c:
    dpi = st.select_slider("Render DPI", [80, 110, 150], 110)

# Probe the current page: repeated words are watermark candidates, and the
# exact hit count tells you whether your string will match anything.
doc_probe = fitz.open(stream=data, filetype="pdf")
pg = doc_probe[page - 1]
words = pg.get_text().split()
from collections import Counter
cands = [(w, c) for w, c in Counter(words).most_common(15)
         if c >= 2 and len(w) > 3]
hits = len(pg.search_for(wm)) if wm else 0
ann_n = sum(1 for _ in (pg.annots() or []))
doc_probe.close()
st.caption(f"annots on page: {ann_n} · `search_for` hits for {wm!r}: **{hits}**")
if wm and hits == 0:
    st.warning("That string occurs 0 times as real text — if you can SEE a "
               "watermark, it is drawn as vector outlines/images, not text, "
               "and no text search will ever match it. Read the candidates "
               "above or tell me what it looks like.")
if cands:
    st.caption("repeated-word candidates: "
               + ", ".join(f"{w} (×{c})" for w, c in cands))

rm_annots = st.checkbox("Delete annotations", True)
redact = st.checkbox("Redact watermark text", True)
col_d, col_e = st.columns(2)
with col_d:
    rm_imgs = st.checkbox("Remove chrome images", True)
with col_e:
    min_pg = st.number_input("Repeat threshold (pages)", 2, n_pages, 3)

col_g, col_h = st.columns(2)
with col_g:
    rm_bg = st.checkbox("Replace full-page background with white", False)
with col_h:
    bg_safe = st.checkbox("Background safe mode (needs text layer)", True)

col_i, col_j = st.columns(2)
with col_i:
    bg_cov = st.slider("Background coverage threshold", 0.5, 0.95, 0.7)
with col_j:
    rm_pat = st.checkbox("Whiten light-gray pattern fills", True)

col_k, _ = st.columns(2)
with col_k:
    pat_gray = st.slider("Pattern gray threshold (below = kept)", 0.3, 0.95, 0.6)

doc_probe4 = fitz.open(stream=data, filetype="pdf")
gp = _gray_patterns(doc_probe4, min_gray=pat_gray)
doc_probe4.close()
st.caption(f"light-gray patterns (≥{pat_gray}): **{len(gp)}**")

doc_probe3 = fitz.open(stream=data, filetype="pdf")
bg_ok, bg_skip = _page_backgrounds(doc_probe3, coverage=bg_cov,
                                   safe_mode=bg_safe, min_pages=1)
doc_probe3.close()
st.caption(f"full-page background candidates: **{len(bg_ok)}**"
           + (f" ({bg_skip} skipped: no text layer or figure-sized use)"
              if bg_skip else ""))
st.caption("Coverage alone cannot tell a dirty background from a legitimate "
           "full-page figure — confirm in the side-by-side before trusting it.")

# Probe chrome content before running.
doc_probe2 = fitz.open(stream=data, filetype="pdf")
ci = _chrome_images(doc_probe2, min_pg)
doc_probe2.close()
st.caption(f"chrome images (≥{min_pg} pages): **{len(ci)}**")

if st.button("Run clean", type="primary"):
    with tempfile.TemporaryDirectory() as tmp:
        inp = str(Path(tmp) / "in.pdf")
        outp = str(Path(tmp) / "out.pdf")
        Path(inp).write_bytes(data)
        try:
            rep = clean_pdf_canvas(
                inp, outp, wm, remove_annots=rm_annots,
                redact_text=redact, remove_chrome_images=rm_imgs,
                min_pages=min_pg, replace_background=rm_bg,
                bg_safe_mode=bg_safe, bg_coverage=bg_cov, bg_min_pages=1,
                whiten_patterns=rm_pat, pattern_gray=pat_gray)
            st.session_state["cleaned"] = Path(outp).read_bytes()
            st.session_state["report"] = rep
        except Exception as e:
            st.error(f"clean failed: {e}")
            st.stop()
if st.session_state.get("report") is not None:
    r = st.session_state["report"]
    st.success(f"removed: {r['annots']} annots · {r['text_hits']} text hits · "
               f"{r['chrome_images']} chrome images · "
               f"{r['backgrounds']} backgrounds whitened · "
               f"{r['patterns']} gray patterns whitened "
               f"({r['chrome_skipped']} inline skipped, "
               f"{r['bg_skipped']} bg skipped, {r['pages']} pages)")

left, right = st.columns(2)
with left:
    st.subheader("Input (original)")
    st.image(render_page(data, page, dpi), use_container_width=True)
with right:
    st.subheader("Output (cleaned)")
    if st.session_state.get("cleaned") is not None:
        st.image(render_page(st.session_state["cleaned"], page, dpi),
                 use_container_width=True)
        st.download_button("Download cleaned PDF", st.session_state["cleaned"],
                           file_name="cleaned.pdf", mime="application/pdf")
    else:
        st.info("Press **Run clean**, then flip pages here to compare.")
