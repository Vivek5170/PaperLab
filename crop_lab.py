"""Crop Lab -- visual testing tool for snap vs vector-assist. No LLM, no DB.

Run:  streamlit run crop_lab.py --server.port 8502
Pick a PDF + page, CLICK-DRAG a box on the page (or type coordinates),
pick a mode, and see what the crop pipeline would do with it. Overlays show
every element type on a dimmed page so colours never clash with the figure.
Nothing is saved anywhere; previews only.
"""
from __future__ import annotations

import io
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from PIL import Image, ImageDraw

import tools_extractor as te

try:
    from streamlit_image_coordinates import streamlit_image_coordinates as sic

    HAS_SIC = True
except ImportError:
    HAS_SIC = False

st.set_page_config(page_title="Crop Lab", layout="wide")
st.title("🔬 Crop Lab — snap vs assist, side by side")

# ---------- PDF + page selection ----------
data_root = Path("data")
pdfs = sorted(str(p) for p in data_root.rglob("*.pdf")) if data_root.exists() else []
choice = st.sidebar.selectbox("PDF", ["(upload one)"] + pdfs)
if choice == "(upload one)":
    uploaded = st.sidebar.file_uploader("Upload PDF", type="pdf")
    if uploaded is None:
        st.info("Pick a PDF from data/ or upload one to start.")
        st.stop()
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in uploaded.name)
    pdf_path = f"/tmp/crop_lab_{safe}_{uploaded.size}.pdf"
    Path(pdf_path).write_bytes(uploaded.getvalue())
    # A new file under a recycled path would reuse stale fingerprints.
    if st.session_state.get("lab_pdf") != pdf_path:
        for cache in (te._CHROME_STROKES, te._CHROME_TEXT, te._PAGE_VEC_CACHE,
                      te._CHROME_CACHE, te._SNAP_CACHE):
            cache.clear()
        st.session_state["lab_pdf"] = pdf_path
        st.session_state["page"] = 1
        st.session_state["ckey"] = st.session_state.get("ckey", 0) + 1
        st.session_state.pop("result", None)
else:
    pdf_path = choice
    if st.session_state.get("lab_pdf") != pdf_path:
        st.session_state["lab_pdf"] = pdf_path
        st.session_state["page"] = 1
        st.session_state["ckey"] = st.session_state.get("ckey", 0) + 1
        st.session_state.pop("result", None)
doc = fitz.open(pdf_path)
n_pages = len(doc)
st.session_state["npages"] = n_pages
st.session_state.setdefault("page", 1)
if st.session_state["page"] > n_pages:
    st.session_state["page"] = n_pages


def _go(d):
    st.session_state.page = min(
        max(1, st.session_state.get("page", 1) + d),
        st.session_state.get("npages", 1),
    )


page_number = st.sidebar.number_input("Page", 1, n_pages, key="page")
c_prev, c_next = st.sidebar.columns(2)
c_prev.button("◀ Prev", on_click=_go, args=(-1,))
c_next.button("Next ▶", on_click=_go, args=(1,))
page = doc[page_number - 1]
W, H = page.rect.width, page.rect.height

# page switch clears the stale result + remounts the canvas
if st.session_state.get("lab_page") != page_number:
    st.session_state["lab_page"] = page_number
    st.session_state.pop("result", None)
    st.session_state["ckey"] = st.session_state.get("ckey", 0) + 1

mode = st.sidebar.radio("Mode", ["assist (vector)", "snap"])


def _reset_box():
    st.session_state.update(x0=100, y0=100, x1=900, y1=900)
    st.session_state["ckey"] = st.session_state.get("ckey", 0) + 1
    st.session_state.pop("result", None)


def _clear_caches():
    for cache in (te._CHROME_STROKES, te._CHROME_TEXT, te._PAGE_VEC_CACHE,
                  te._CHROME_CACHE, te._SNAP_CACHE):
        cache.clear()
    st.session_state.pop("result", None)


st.sidebar.button("🧹 Reset box", on_click=_reset_box)
st.sidebar.button("🗑 Clear caches", on_click=_clear_caches)

# ---------- box state (canvas writes these before the inputs exist) ----------
st.session_state.setdefault("x0", 100)
st.session_state.setdefault("y0", 100)
st.session_state.setdefault("x1", 900)
st.session_state.setdefault("y1", 900)

# ---------- type overlays ----------
st.sidebar.subheader("Overlays (what each thing is)")
LAYERS = st.sidebar.multiselect(
    "Show on page",
    ["stroke clusters", "chrome strokes", "long text", "short text",
     "chrome text", "embedded images"],
    default=["stroke clusters", "long text", "short text", "embedded images"],
)
dim = st.sidebar.checkbox("Dim page under overlays", value=True)
st.sidebar.caption(
    "Page dims to grey so no overlay colour can be mistaken for figure ink. "
    "One colour per meaning: 🩵 ALL stroke clusters (C0/C1… labels tell them "
    "apart) · 🟥 chrome strokes only · 🟧 long text · 🟩 short text · "
    "⬜ chrome text · 🟪 embedded images (img:xref)"
)


# Fixed categorical palette: one colour per meaning, never reused.
# Clusters share a single cyan (C0/C1 labels tell them apart) so no cluster
# ever renders red/yellow and clashes with chrome or text.
CLUSTER_COL = (0, 220, 255)      # every stroke cluster
CHROME_COL = (255, 60, 60)       # chrome strokes (and chrome images)
LONG_TEXT_COL = (255, 170, 0)    # long text (trim candidates)
SHORT_TEXT_COL = (40, 220, 90)   # short text (labels)
CHROME_TEXT_COL = (200, 200, 200)  # chrome text
IMAGE_COL = (190, 80, 255)       # embedded images


def _pt_to_px(x, y, img_w, img_h):
    return x / W * img_w, y / H * img_h


def _apply_overlays(img):
    """Draw the selected type layers. Page is dimmed first when asked, so
    overlay colours can never be confused with the original figure colours."""
    if not LAYERS:
        return img
    with st.spinner("Reading page vectors (chrome scan on first use)…"):
        _s, blocks_nc, clusters = te._page_vectors(pdf_path, page_number)
        chrome_s, chrome_t = te._chrome_for(pdf_path)
    d = fitz.open(pdf_path)
    try:
        pg = d[page_number - 1]
        drawings = [x["rect"] for x in pg.get_drawings()]
        raw_blocks = [b for b in pg.get_text("blocks") if str(b[4]).strip()]
        images = []
        img_chrome = te._chrome_xrefs(pdf_path)
        for im in pg.get_images(full=True):
            if im[0] == 0:
                continue
            for rect in pg.get_image_rects(im[0]):
                images.append((im[0], rect, im[0] in img_chrome))
    finally:
        d.close()

    out = img.copy()
    if dim:
        out = out.convert("L").point(lambda v: int(v * 0.4)).convert("RGB")
    iw, ih = out.size
    dr = ImageDraw.Draw(out)

    def rect_pts(r):
        x0, y0 = _pt_to_px(r.x0, r.y0, iw, ih)
        x1, y1 = _pt_to_px(r.x1, r.y1, iw, ih)
        return [x0, y0, x1, y1]

    def label(x, y, text, col):
        dr.rectangle([x, y, x + 7 * len(text) + 6, y + 14], fill=(20, 20, 20))
        dr.text((x + 3, y + 1), text, fill=col)

    if "chrome strokes" in LAYERS:
        for r in drawings:
            if te._stroke_fp(r) in chrome_s:
                dr.rectangle(rect_pts(r), outline=CHROME_COL, width=3)
    if "stroke clusters" in LAYERS:
        for i, (cbox, members) in enumerate(clusters):
            for m in members:
                dr.rectangle(rect_pts(m), outline=CLUSTER_COL, width=1)
            dr.rectangle(rect_pts(cbox), outline=CLUSTER_COL, width=4)
            x, y = _pt_to_px(cbox.x0, cbox.y0, iw, ih)
            label(x, y - 16, f"C{i}", (255, 255, 255))
    if "long text" in LAYERS or "short text" in LAYERS:
        for b in blocks_nc:
            words = len(str(b[4]).split())
            rr = fitz.Rect(b[0], b[1], b[2], b[3])
            if words > te._VEC_TRIM_WORDS and "long text" in LAYERS:
                dr.rectangle(rect_pts(rr), outline=LONG_TEXT_COL, width=3)
            elif words <= te._VEC_TRIM_WORDS and "short text" in LAYERS:
                dr.rectangle(rect_pts(rr), outline=SHORT_TEXT_COL, width=3)
    if "chrome text" in LAYERS:
        for b in raw_blocks:
            if te._block_fp(b) in chrome_t:
                rr = fitz.Rect(b[0], b[1], b[2], b[3])
                dr.rectangle(rect_pts(rr), outline=CHROME_TEXT_COL, width=3)
    if "embedded images" in LAYERS:
        for xref, r, is_chrome in images:
            col = CHROME_COL if is_chrome else IMAGE_COL
            dr.rectangle(rect_pts(r), outline=col, width=4)
            x, y = _pt_to_px(r.x0, r.y0, iw, ih)
            label(x, y - 16, f"img:{xref}", col)
    return out


# ---------- page render ----------
DISP = 900
zoom = DISP / max(W, H)
pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
page_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def to_px(b, img_w, img_h):
    return (
        b[0] / 1000 * img_w,
        b[1] / 1000 * img_h,
        b[2] / 1000 * img_w,
        b[3] / 1000 * img_h,
    )


# ---------- modes (pure helpers: no DB, no LLM, no saves) ----------
def _run_snap():
    norm = [(int(x), int(y)) for x, y in norm_pts]
    hit = te._try_snap(pdf_path, page_number, norm)
    doc2 = fitz.open(pdf_path)
    pg = doc2[page_number - 1]
    r = pg.rect
    want = fitz.Rect(x0 / 1000 * r.width, y0 / 1000 * r.height,
                     x1 / 1000 * r.width, y1 / 1000 * r.height)
    chrome = te._chrome_xrefs(pdf_path)
    rows = []
    for img in pg.get_images(full=True):
        xref = img[0]
        if xref == 0 or xref in chrome:
            continue
        for rect in pg.get_image_rects(xref):
            ix = max(0, min(want.x1, rect.x1) - max(want.x0, rect.x0))
            iy = max(0, min(want.y1, rect.y1) - max(want.y0, rect.y0))
            inter = max(0, ix) * max(0, iy)
            union = want.width * want.height + rect.width * rect.height - inter
            iou = inter / union if union else 0
            cov = inter / (rect.width * rect.height) if rect.width * rect.height else 0
            rows.append({
                "xref": xref,
                "image rect (pt)": [round(v) for v in rect],
                "IoU": round(iou, 3),
                "coverage": round(cov, 3),
            })
    rows.sort(key=lambda d: -d["IoU"])
    doc2.close()
    preview = None
    if hit is not None:
        ext, data, xref = hit
        try:
            preview = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            preview = None
    return {"mode": "snap", "hit": hit is not None, "rows": rows[:8],
            "preview": preview, "final1000": None,
            "box1000": [x0, y0, x1, y1], "page": page_number,
            "text": ("matched xref %d, original bytes" % hit[2]) if hit else "no match — would fall through to assist/plain"}


def _run_assist():
    norm = [(int(x), int(y)) for x, y in norm_pts]
    _s, blocks, clusters = te._page_vectors(pdf_path, page_number)
    doc2 = fitz.open(pdf_path)
    pg = doc2[page_number - 1]
    r = pg.rect
    want = fitz.Rect(x0 / 1000 * r.width, y0 / 1000 * r.height,
                     x1 / 1000 * r.width, y1 / 1000 * r.height)
    out = te._assist_box(pg, want, blocks, clusters)
    doc2.close()
    if out is None:
        return {"mode": "assist", "hit": False, "final1000": None,
                "preview": None, "rows": [], "verdicts": [],
                "your1000": [x0, y0, x1, y1], "page": page_number,
                "text": "no strokes touch your box — would save plain crop of your box"}
    final, trims, capped, verdicts = out
    page_rect = fitz.Rect(0, 0, r.width, r.height)
    final1000 = te._to_1000(final, page_rect)
    your1000 = [x0, y0, x1, y1]
    if capped is not None:
        text = ("strokes continue far beyond your box (to %s); not applied. "
                "Re-crop if you want that." % te._to_1000(capped, page_rect))
    else:
        bits = []
        for edge, i in (("left", 0), ("top", 1), ("right", 2), ("bottom", 3)):
            dlt = final1000[i] - your1000[i]
            if edge in ("left", "top"):
                dlt = -dlt
            if dlt >= te._MIN_REPORT_DELTA:
                bits.append(f"extended {edge} by {dlt} (strokes)")
            elif dlt <= -te._MIN_REPORT_DELTA:
                bits.append(f"trimmed {edge} by {-dlt}")
        for edge, snip in trims:
            for k, c in enumerate(bits):
                if c.startswith(f"trimmed {edge} by") and "(text" not in c and "(empty" not in c:
                    bits[k] = c + (f' (text: "{snip}")' if snip else " (empty margin)")
                    break
        text = ("changes: %s" % "; ".join(bits)) if bits else "no change needed"
    rb = te._inflate(fitz.Rect(
        final1000[0] / 1000 * r.width, final1000[1] / 1000 * r.height,
        final1000[2] / 1000 * r.width, final1000[3] / 1000 * r.height,
    ), te._VEC_PAD)
    rb &= page_rect
    crop = te._clip_render_to_pil(pdf_path, page_number, rb)
    return {"mode": "assist", "hit": True, "final1000": final1000,
            "your1000": your1000, "preview": crop, "rows": [],
            "verdicts": verdicts, "page": page_number, "text": text}


def _show_result(result):
    boxkey = "your1000" if "your1000" in result else "box1000"
    if result.get("page") != page_number or result.get(boxkey) != [x0, y0, x1, y1]:
        st.warning("⚠ box or page changed since this result — hit Run again.")
    st.subheader(f"mode: {result['mode']} — {result['text']}")
    if result["mode"] == "snap":
        if result["rows"]:
            st.table(result["rows"])
        else:
            st.caption("no embedded (non-chrome) images on this page")
        if result["preview"] is not None:
            st.image(result["preview"], caption="snapped original bytes")
    else:
        if result["final1000"]:
            st.code(f"your box:  {result['your1000']}\nfinal box: {result['final1000']}")
            st.image(result["preview"], caption="final crop (no pad, 250 DPI)")
            if result.get("verdicts"):
                st.subheader("leftover text — why each block survived")
                st.table([{"text": v[0], "words": v[1], "verdict": v[2]}
                          for v in result["verdicts"]])
        else:
            st.caption("plain fallback would apply")


# ---------- layout: drawable page + precise box inputs ----------
col_page, col_out = st.columns(2)
with col_page:
    st.subheader(f"Page {page_number} ({W:.0f}×{H:.0f}pt)")
    annotated = _apply_overlays(page_img)
    if HAS_SIC:
        CW = 720
        disp = annotated.resize((CW, int(CW * H / W)))
        CH = disp.height
        # bake the boxes in so you can see them while dragging a new one:
        # red = your current box, green = last final box
        _ov = ImageDraw.Draw(disp)
        _cx0, _cy0 = st.session_state.x0, st.session_state.y0
        _cx1, _cy1 = st.session_state.x1, st.session_state.y1
        _ov.rectangle(
            [_cx0 / 1000 * CW, _cy0 / 1000 * CH,
             _cx1 / 1000 * CW, _cy1 / 1000 * CH],
            outline=(255, 30, 30), width=3,
        )
        if (res := st.session_state.get("result")) and res.get("final1000"):
            _f = res["final1000"]
            _ov.rectangle(
                [_f[0] / 1000 * CW, _f[1] / 1000 * CH,
                 _f[2] / 1000 * CW, _f[3] / 1000 * CH],
                outline=(50, 255, 90), width=3,
            )
            st.caption("red = your box · green = final box")
        val = sic(
            disp, width=CW,
            key=f"sic_{pdf_path}_{page_number}_{st.session_state.get('ckey', 0)}",
            click_and_drag=True, cursor="crosshair",
        )
        if isinstance(val, dict) and val != st.session_state.get("last_sic"):
            st.session_state["last_sic"] = dict(val)
            if {"x1", "y1", "x2", "y2"} <= set(val):
                nx0 = min(max(val["x1"] / CW * 1000, 0), 1000)
                ny0 = min(max(val["y1"] / CH * 1000, 0), 1000)
                nx1 = min(max(val["x2"] / CW * 1000, 0), 1000)
                ny1 = min(max(val["y2"] / CH * 1000, 0), 1000)
                if abs(nx1 - nx0) >= 5 and abs(ny1 - ny0) >= 5:
                    st.session_state.update(
                        x0=int(round(min(nx0, nx1))), y0=int(round(min(ny0, ny1))),
                        x1=int(round(max(nx0, nx1))), y1=int(round(max(ny0, ny1))),
                    )
        st.caption("Click-drag a rectangle on the page. Numbers below fine-tune it.")
    else:
        st.warning("pip install streamlit-image-coordinates for click-drag drawing.")
        overlay = annotated
        d = ImageDraw.Draw(overlay)
        _fx0, _fy0 = st.session_state.x0, st.session_state.y0
        _fx1, _fy1 = st.session_state.x1, st.session_state.y1
        d.rectangle(to_px((_fx0, _fy0, _fx1, _fy1), *overlay.size), outline="red", width=3)
        if (res := st.session_state.get("result")) and res.get("final1000"):
            d.rectangle(to_px(res["final1000"], *overlay.size), outline="lime", width=3)
            st.caption("red = your box · green = final box")
        st.image(overlay, use_container_width=True)
    x0, y0, x1, y1 = (st.session_state.x0, st.session_state.y0,
                      st.session_state.x1, st.session_state.y1)

# ---------- precise box inputs (sidebar, after canvas so state is fresh) ----------
st.sidebar.subheader("Your box (0-1000) — canvas or type")
x0 = st.sidebar.number_input("x0", 0, 1000, key="x0")
y0 = st.sidebar.number_input("y0", 0, 1000, key="y0")
x1 = st.sidebar.number_input("x1", 0, 1000, key="x1")
y1 = st.sidebar.number_input("y1", 0, 1000, key="y1")
x0, x1 = min(x0, x1), max(x0, x1)
y0, y1 = min(y0, y1), max(y0, y1)
st.sidebar.caption(
    f"points: ({x0 / 1000 * W:.0f}, {y0 / 1000 * H:.0f}) – "
    f"({x1 / 1000 * W:.0f}, {y1 / 1000 * H:.0f})"
)
norm_pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

with col_out:
    if st.sidebar.button("▶ Run", type="primary"):
        with st.spinner("Working (chrome scan on first call can take a bit)…"):
            out = _run_snap() if mode == "snap" else _run_assist()
        st.session_state["result"] = out
        st.rerun()
    elif (res := st.session_state.get("result")):
        _show_result(res)
    else:
        st.info("Draw a box, pick a mode, hit Run.")

doc.close()
