"""Question/solution rendering: KaTeX-first with a compiled-PNG fallback.

Primary path splits the .tex into text chunks (shown as markdown, where
$...$ math renders via KaTeX) and figure references (shown as images).
Fallback path compiles the fragment with tectonic (article class only --
works offline) and renders the PDF page to PNG via PyMuPDF, cached next to
the .tex file. The fallback button is only offered when tectonic proves
capable (one probe compile per process).
"""

from __future__ import annotations

import functools
import re
import subprocess
import tempfile
from pathlib import Path

INCLUDEGRAPHIC_RE = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^}]+)\}"
)


def _split_math(text):
    """Split text into ("text", s) and ("math", inner, display) parts.

    Pairing rules: $$...$$ and \\[...\\] are display blocks (must be closed
    to count). A single $ opens math only if the next char is a non-space,
    non-digit (so "$5 and ..." prices don't open a span); it closes only on
    a $ preceded by a non-space. A $ that never pairs is escaped to \\$ so
    KaTeX renders it literally instead of swallowing the block.
    """
    out = []
    buf = []
    i, n = 0, len(text)

    def flush():
        if buf:
            out.append(("text", "".join(buf)))
            buf.clear()

    while i < n:
        if text[i] == "\\" and text[i + 1 : i + 2] == "$":
            buf.append("\x00DOL\x00")  # escaped dollar: literal, never math
            i += 2
        elif text.startswith("$$", i):
            j = text.find("$$", i + 2)
            if j == -1:
                buf.append(text[i:])
                break
            flush()
            out.append(("math", text[i + 2 : j].strip(), True))
            i = j + 2
        elif text.startswith("\\[", i):
            j = text.find("\\]", i + 2)
            if j == -1:
                buf.append(text[i:])
                break
            flush()
            out.append(("math", text[i + 2 : j].strip(), True))
            i = j + 2
        elif text[i] == "$":
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt and not nxt.isspace() and not nxt.isdigit():
                k, found = i + 1, -1
                while True:
                    k = text.find("$", k)
                    if k == -1:
                        break
                    if text[k + 1 : k + 2] == "$":
                        k += 2
                        continue
                    if not text[k - 1].isspace():
                        found = k
                        break
                    k += 1
                if found != -1:
                    flush()
                    out.append(("math", text[i + 1 : found], False))
                    i = found + 1
                    continue
            buf.append("\\$")
            i += 1
        else:
            buf.append(text[i])
            i += 1
    flush()
    return out


def _text_chunk_to_markdown(chunk: str) -> str:
    """Convert a non-math chunk; strip newlines only, never spaces."""
    s = chunk
    s = s.replace(r"\%", "\x00PERC\x00").replace(r"\&", "\x00AMP\x00")
    s = s.replace(r"\$", "\x00DOL\x00").replace(r"\{", "\x00LB\x00").replace(
        r"\}", "\x00RB\x00")
    # LaTeX comments are invisible in rendered output: drop them, except
    # "% Answer: ..." key lines, shown as bold key text for the reader.
    kept = []
    for line in s.split("\n"):
        ls = line.lstrip()
        if ls.startswith("%"):
            m = re.match(r"%\s*answer\s*:(.*)", ls, re.IGNORECASE)
            if m:
                kept.append("**Answer:** " + m.group(1).strip())
            continue
        kept.append(re.sub(r"%.*$", "", line))
    s = "\n".join(kept)
    s = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", s)
    s = re.sub(r"\\textit\{([^{}]*)\}", r"*\1*", s)
    s = re.sub(r"\\emph\{([^{}]*)\}", r"*\1*", s)
    s = re.sub(r"\\(?:hspace|vspace)\{[^}]*\}", " ", s)
    s = re.sub(r"\\(?:quad|qquad|[,;:!]| )", " ", s)
    s = re.sub(r"\\begin\{(?:center|flushleft|flushright)\}", "", s)
    s = re.sub(r"\\end\{(?:center|flushleft|flushright)\}", "", s)
    s = s.replace("\\\\", "\n").replace("\\newline", "\n").replace("\\noindent", "")
    s = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(\{[^{}]*\})?", "", s)
    for tok, ch in (("\x00PERC\x00", "%"), ("\x00AMP\x00", "&"),
                    ("\x00DOL\x00", "$"), ("\x00LB\x00", "{"),
                    ("\x00RB\x00", "}")):
        s = s.replace(tok, ch)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s  # no stripping here: edge newlines separate this chunk from
    # neighbouring math spans; only the final document gets stripped.


def _underline_plain(m: "re.Match") -> str:
    """Wrap a bare \\underline{...} as KaTeX; \\text for plain words."""
    inner = m.group(1)
    if "\\" in inner:
        return "$\\underline{%s}$" % inner
    return "$\\underline{\\text{%s}}$" % inner


def tex_to_markdown(chunk: str) -> str:
    """Best-effort LaTeX -> markdown. Math spans pass through untouched,
    except: \\[...\\] becomes $$...$$ (Streamlit has no \\[ support) and
    \\dfrac becomes \\frac inside single-$ inline spans (display fractions
    wreck inline line rhythm). \\underline{...} headings become KaTeX
    ($\\underline{...}$) since raw HTML is escaped by Streamlit."""
    # Headings first, so they enter the splitter as balanced math spans.
    chunk = re.sub(
        r"\\underline\{\s*\\textbf\{([^{}]*)\}\s*\}",
        r"$\\underline{\\textbf{\1}}$", chunk)
    chunk = re.sub(r"\\underline\{([^{}]*)\}", _underline_plain, chunk)
    parts = _split_math(chunk)
    out = []
    for kind, *rest in parts:
        if kind == "math":
            inner, display = rest
            if display:
                out.append("\n\n$$" + inner + "$$\n\n")
            else:
                out.append("$" + inner.replace("\\dfrac", "\\frac") + "$")
        else:
            out.append(_text_chunk_to_markdown(rest[0]))
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()


def split_tex(tex: str, base_dir: str | Path) -> list[tuple[str, str]]:
    """Split tex into [("text", markdown), ("fig", abspath)] segments."""
    base = Path(base_dir)
    segments: list[tuple[str, str]] = []
    pos = 0
    for m in INCLUDEGRAPHIC_RE.finditer(tex):
        before = tex[pos:m.start()].strip()
        if before:
            segments.append(("text", tex_to_markdown(before)))
        fig = (base / m.group("path")).resolve()
        segments.append(("fig", str(fig) if fig.is_file() else ""))
        pos = m.end()
    tail = tex[pos:].strip()
    if tail:
        segments.append(("text", tex_to_markdown(tail)))
    return segments


@functools.lru_cache(maxsize=1)
def tex_engine_available() -> bool:
    """Probe once per process: can tectonic compile a trivial document?"""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "probe.tex"
            src.write_text(
                "\\documentclass{article}\\begin{document}hi\\end{document}\n"
            )
            r = subprocess.run(
                ["tectonic", "-o", tmp, str(src)],
                capture_output=True, text=True, timeout=60,
            )
            return r.returncode == 0 and (Path(tmp) / "probe.pdf").exists()
    except Exception:
        return False


# Bump when the viewer wrapper changes: the PNG cache digest folds this in,
# so stale renders (old margins / page numbers) recompile automatically.
_WRAPPER_REV = "v2-empty-small-vertical"

# Pixels of breathing room kept above/below content after the vertical trim.
_TRIM_PAD = 15


def _trim_vertical_whitespace(img):
    """Crop top/bottom all-white bands; keep full page width.

    Uniform width across questions (no per-image stretch in the viewer);
    only the dead space above/below content goes away.
    """
    import numpy as np

    a = np.asarray(img.convert("L"))
    rows = np.where((a < 250).any(axis=1))[0]
    if not len(rows):
        return img
    top = max(0, int(rows.min()) - _TRIM_PAD)
    bot = min(img.height, int(rows.max()) + 1 + _TRIM_PAD)
    return img.crop((0, top, img.width, bot))


def _fig_bytes_for_hash(work_dir: str | Path, tex_path: str) -> bytes:
    """Raw bytes of a figure referenced by the tex (b"" if unresolvable)."""
    try:
        p = Path(work_dir) / tex_path
        return p.read_bytes() if p.is_file() else b""
    except OSError:
        return b""


def render_tex_to_png(tex: str, work_dir: str | Path, out_name: str) -> Path | None:
    """Compile a tex fragment to PNG (article class only). Cached by mtime.

    Returns the PNG path, or None if the engine cannot do it here.
    """
    if not tex_engine_available():
        return None
    work = Path(work_dir)
    out = work / out_name
    marker = work / (out_name + ".src_hash")
    import hashlib
    import shutil

    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    # Digest covers the tex, the wrapper revision, AND every referenced
    # figure's bytes: swapping a crop with identical tex must recompile.
    h = hashlib.sha256((_WRAPPER_REV + "\n" + tex).encode())
    for m in INCLUDEGRAPHIC_RE.finditer(tex):
        h.update(m.group("path").encode())
        h.update(_fig_bytes_for_hash(work, m.group("path")))
    digest = h.hexdigest()
    if out.exists() and marker.exists() and marker.read_text() == digest:
        return out
    doc = ("\\documentclass{article}\n\\usepackage{amsmath,amssymb,graphicx}\n"
           "\\begin{document}\n\\pagestyle{empty}\n\\small\n"
           + tex + "\n\\end{document}\n")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            # Tectonic only reads files under the input file's directory,
            # so stage the wrapper .tex plus any referenced figures together.
            work_resolved = work.resolve()
            for m in INCLUDEGRAPHIC_RE.finditer(tex):
                src = (work / m.group("path")).resolve()
                if src.is_file():
                    rel = src.relative_to(work_resolved) if _is_within(src, work_resolved) else Path(src.name)
                    dest = Path(tmp) / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
            src = Path(tmp) / "view.tex"
            src.write_text(doc, encoding="utf-8")
            r = subprocess.run(
                ["tectonic", "-o", tmp, str(src)],
                capture_output=True, text=True, timeout=120, cwd=tmp,
            )
            pdf = Path(tmp) / "view.pdf"
            if r.returncode != 0 or not pdf.exists():
                return None
            import fitz

            d = fitz.open(str(pdf))
            try:
                pix = d[0].get_pixmap(dpi=150)
                # Vertical trim only: dead space above/below content goes,
                # full page width stays for a uniform look in the viewer.
                from PIL import Image

                w, h = pix.width, pix.height
                img = Image.frombytes("RGB", (w, h), pix.samples)
                img = _trim_vertical_whitespace(img)
                img.save(str(out), format="PNG")
            finally:
                d.close()
        marker.write_text(digest)
        return out
    except Exception:
        return None
