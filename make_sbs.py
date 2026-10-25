"""Side-by-side verification: LEFT=original, RIGHT=best-for-cropping.

Best = pdf_clean.clean_pdf_canvas + pdf_longtext.strip_long_text.
One output PDF per archive PDF, each page doubled in width.

Run: python3 make_sbs.py [--src data/archive] [--out /tmp/longtext_sbs]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

import pdf_clean as pc
from pdf_longtext import strip_long_text


def side_by_side(orig: Path, modified: Path, out: Path) -> int:
    d0, d1 = fitz.open(orig), fitz.open(modified)
    assert len(d0) == len(d1), f"page mismatch {orig.name}"
    dst = fitz.open()
    try:
        for i in range(len(d0)):
            r0, r1 = d0[i].rect, d1[i].rect
            w, h = r0.width + r1.width, max(r0.height, r1.height)
            pg = dst.new_page(width=w, height=h)
            pg.show_pdf_page(fitz.Rect(0, 0, r0.width, h), d0, i)
            pg.show_pdf_page(fitz.Rect(r0.width, 0, w, h), d1, i)
            # divider + labels
            pg.draw_line(fitz.Point(r0.width, 0), fitz.Point(r0.width, h),
                         color=(1, 0, 0), width=1.5)
        dst.save(out, garbage=4, deflate=True)
        return len(d0)
    finally:
        d0.close(); d1.close(); dst.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/archive")
    ap.add_argument("--out", default="/tmp/longtext_sbs")
    ap.add_argument("--aggressive", action="store_true",
                    help="also strip short-line debris far from strokes")
    args = ap.parse_args()
    src, outdir = Path(args.src), Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(src.glob("*.pdf"))
    if not pdfs:
        print(f"no pdfs in {src}", file=sys.stderr)
        return 1
    for pdf in pdfs:
        tag = pdf.stem
        suffix = "_AGGR" if args.aggressive else ""
        dest = outdir / f"SBS_{tag}{suffix}.pdf"
        if dest.is_file():  # resume: skip finished papers
            print(f"SKIP {pdf.name} (exists)")
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cleaned = str(Path(tmp) / "cleaned.pdf")
                stripped = str(Path(tmp) / "stripped.pdf")
                pc.clean_pdf_canvas(str(pdf), cleaned)   # production clean
                strip_long_text(cleaned, stripped,
                                aggressive=args.aggressive)  # + strip
                npages = side_by_side(pdf, Path(stripped), dest)
            print(f"OK {pdf.name} ({npages}p) -> {dest}")
        except Exception as exc:  # fail-open per paper, keep going
            print(f"FAIL {pdf.name}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
