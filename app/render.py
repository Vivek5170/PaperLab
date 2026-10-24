"""Question/solution rendering: KaTeX-first with a compiled-PNG fallback.

Primary path splits the .tex into text chunks (shown as markdown, where
$...$ math renders via KaTeX) and figure references (shown as images).
Fallback path compiles the fragment with tectonic (article class only --
works offline once packages are cached) and renders the PDF to PNG via
PyMuPDF, cached next to the .tex file. The fallback button is only offered
when tectonic proves capable (one probe compile per process).

Display math rule (important): Streamlit reads "$$" followed by text on the
same line as a fence with an info string, and a "$$" glued to the end of a
content line never closes it, so the block swallows the rest of the page.
Every display block is therefore emitted as:

    <blank line>
    $$
    <math on ONE line>
    $$
    <blank line>
"""

from __future__ import annotations

import functools
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

INCLUDEGRAPHIC_RE = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^}]+)\}"
)

# ---------------------------------------------------------------- comments

_ANSWER_COMMENT_RE = re.compile(r"\s*%\s*answer\s*:(.*)", re.IGNORECASE)
_TRAILING_COMMENT_RE = re.compile(r"(?<!\\)%.*$")


def _strip_comments(tex: str) -> str:
    """Drop LaTeX comments BEFORE any math pairing or figure scanning.

    A comment like "% check $x" must not pair its $ with real text, and a
    commented-out \\includegraphics must not show up as a figure. Whole-line
    comments vanish entirely (no blank line is left behind, so a comment
    inside a math span cannot split it into paragraphs). "% Answer: ..."
    lines become a bold key line for the reader.
    """
    out = []
    for line in tex.split("\n"):
        if line.lstrip().startswith("%"):
            m = _ANSWER_COMMENT_RE.match(line)
            if m:
                out.append("**Answer:** " + m.group(1).strip())
                out.append("")
            continue
        out.append(_TRAILING_COMMENT_RE.sub("", line))
    return "\n".join(out)


# ------------------------------------------------------------ math splitting


def _split_math(text):
    """Split text into ("text", s) and ("math", inner, display) parts.

    Pairing rules: $$...$$ and \\[...\\] are display blocks (must be closed
    to count). A single $ opens math if the next char is not whitespace; it
    closes on a $ preceded by a non-space, never across a blank line, and
    skipping escaped \\$. A digit opener ($2\\pi r$, $10^{-3}$) is math,
    unless the span is a bare price-like phrase ("$5 and $6" stays literal).
    A $ that never pairs is escaped to \\$ so it renders literally instead of
    swallowing the block. A "\\\\" row break is consumed as a unit so that
    "\\\\[2pt]" is never mistaken for a "\\[" display opener.
    """
    out = []
    buf = []
    i, n = 0, len(text)

    def flush():
        if buf:
            out.append(("text", "".join(buf)))
            buf.clear()

    while i < n:
        c = text[i]
        if c == "\\" and text[i + 1 : i + 2] == "$":
            buf.append("\x00DOL\x00")  # escaped dollar: literal, never math
            i += 2
        elif c == "\\" and text[i + 1 : i + 2] == "\\":
            buf.append("\\\\")  # row break, consumed as a unit
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
        elif c == "$":
            nxt = text[i + 1] if i + 1 < n else ""
            if nxt and not nxt.isspace():
                k, found = i + 1, -1
                while True:
                    k = text.find("$", k)
                    if k == -1 or "\n\n" in text[i:k]:  # never pair across paragraphs
                        break
                    if text[k - 1] == "\\":  # escaped dollar inside the span
                        k += 1
                        continue
                    if text[k + 1 : k + 3] == "$$":
                        k += 2
                        continue
                    if not text[k - 1].isspace():
                        found = k
                        break
                    # If this dollar is preceded by whitespace and followed by non-whitespace,
                    # it is a new math opener -- the current dollar never closed.
                    if k + 1 < n and not text[k + 1].isspace():
                        break
                    k += 1
                if found != -1:
                    inner = text[i + 1 : found]
                    is_bare_price = (
                        nxt.isdigit()
                        and re.search(r"\b(?:and|or|for|to|with|the|in|at|of|is|per|each)\b", inner, re.IGNORECASE)
                        and not re.search(r"[\\^_{}=+\-*/<>~]", inner)
                    )
                    if not is_bare_price:
                        flush()
                        out.append(("math", inner, False))
                        i = found + 1
                        continue
            buf.append("\\$")
            i += 1
        else:
            buf.append(c)
            i += 1
    flush()
    return out


def _display_block(inner: str) -> str:
    """Display math as a fenced block: $$ on its own lines, math on one line.

    Collapsing whitespace is harmless to KaTeX (\\\\ row separators carry the
    structure) and removes every blank-line / indentation hazard. Row
    separators (\\\\) are doubled to \\\\\\\\ so markdown-it (halving escapes)
    delivers \\\\ to KaTeX.
    """
    inner = inner.replace("\\\\", "\\\\\\\\")
    one_line = " ".join(inner.split())
    if not one_line:
        return ""
    return "\n\n$$\n" + one_line + "\n$$\n\n"


# ---------------------------------------------------------- text conversion

# Commands whose braced argument is dropped; every other \cmd{arg} keeps arg
# (so \text{kg} or \textrm{...} outside math never silently loses content).
_DROP_ARG = {
    "label", "ref", "eqref", "cite", "vspace", "hspace", "pagebreak",
    "newpage", "begin", "end",
}
_CMD_RE = re.compile(r"\\([a-zA-Z]+)\*?(?:\[[^\]]*\](?=\{))?(\{[^{}]*\})?")
_ROW_BREAK_RE = re.compile(
    r"\\\\(?:\[\s*-?[\d.]+\s*(?:pt|mm|cm|em|ex|in)\s*\])?"
)


def _cmd_sub(m: "re.Match") -> str:
    name, arg = m.group(1), m.group(2)
    if arg and name not in _DROP_ARG:
        return arg[1:-1]
    return ""


def _text_chunk_to_markdown(chunk: str) -> str:
    """Convert a non-math chunk; strip newlines only, never edge spaces."""
    s = chunk
    s = s.replace(r"\%", "\x00PERC\x00").replace(r"\&", "\x00AMP\x00")
    s = s.replace(r"\$", "\x00DOL\x00").replace(r"\{", "\x00LB\x00").replace(
        r"\}", "\x00RB\x00")
    s = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", s)
    s = re.sub(r"\\textit\{([^{}]*)\}", r"*\1*", s)
    s = re.sub(r"\\emph\{([^{}]*)\}", r"*\1*", s)
    s = re.sub(r"\\(?:hspace|vspace)\{[^}]*\}", " ", s)
    s = re.sub(r"\\(?:quad|qquad|[,;:!]| )", " ", s)
    s = re.sub(r"\\begin\{(?:center|flushleft|flushright)\}", "", s)
    s = re.sub(r"\\end\{(?:center|flushleft|flushright)\}", "", s)
    # Hard line breaks (two trailing spaces + newline): a bare "\n" would be
    # a soft break and render as a space.
    s = _ROW_BREAK_RE.sub("  \n", s)
    s = s.replace("\\newline", "  \n").replace("\\noindent", "")
    s = _CMD_RE.sub(_cmd_sub, s)
    for tok, ch in (("\x00PERC\x00", "%"), ("\x00AMP\x00", "&"),
                    ("\x00DOL\x00", "\\$"), ("\x00LB\x00", "{"),
                    ("\x00RB\x00", "}")):
        s = s.replace(tok, ch)
    # Indented lines (4+ spaces) would become markdown code blocks. Only
    # strip after a newline: a chunk's first line continues a line that
    # started before the neighbouring math span, so its spaces must stay.
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s


def _underline_plain(m: "re.Match") -> str:
    """Wrap a bare \\underline{...} as KaTeX; \\text for plain words."""
    inner = m.group(1)
    if "\\" in inner:
        return "$\\underline{%s}$" % inner
    return "$\\underline{\\text{%s}}$" % inner


_ENUMERATE_RE = re.compile(
    r"\\begin\{enumerate\}(?:\[[^\]]*\])?(.*?)\\end\{enumerate\}",
    re.DOTALL,
)


def _render_enumerate(m: "re.Match") -> str:
    """enumerate -> A) B) C) ... markdown items (labels become the counter)."""
    parts = re.split(r"\\item(?:\[[^\]]*\])?", m.group(1))
    if len(parts) < 2:
        return m.group(1)  # no \item at all: leave inner text untouched
    out = []
    if parts[0].strip():
        out.append(parts[0])
    for i, part in enumerate(parts[1:]):
        marker = "%s) " % chr(ord("A") + i) if i < 26 else "%d. " % (i + 1)
        out.append("\n\n" + marker + part.strip())
    return "".join(out)


_MATH_ENV_RE = re.compile(
    r"(?<!\$)\\begin\{(align\*?|gather\*?|equation\*?|eqnarray\*?|multline\*?)\}(.*?)\\end\{\1\}",
    re.DOTALL,
)
# KaTeX has no align*/gather*/equation*: map each to something it knows.
# aligned|gathered are NOT matched above: they only appear inside math.
_ENV_WRAP = {
    "align": "aligned",
    "eqnarray": "aligned",
    "gather": "gathered",
    "multline": "gathered",
    "equation": None,
}


def _render_math_env(m: "re.Match") -> str:
    """align*/gather*/equation* -> a $$ block (normalised by _display_block)."""
    name = m.group(1).rstrip("*")
    body = m.group(2).strip()
    wrap = _ENV_WRAP.get(name, "aligned")
    if wrap:
        body = "\\begin{" + wrap + "} " + body + " \\end{" + wrap + "}"
    return "\n\n$$" + body + "$$\n\n"


def tex_to_markdown(chunk: str) -> str:
    """Best-effort LaTeX -> markdown.

    Math spans pass through untouched, except: \\[...\\], $$...$$ and
    align-style environments become fenced display blocks (see module
    docstring); \\dfrac becomes \\frac inside inline spans; \\underline{...}
    headings become KaTeX since raw HTML is escaped by Streamlit.
    """
    chunk = _strip_comments(chunk)
    # Headings first, so they enter the splitter as balanced math spans.
    chunk = re.sub(
        r"\\underline\{\s*\\textbf\{([^{}]*)\}\s*\}",
        r"$\\underline{\\textbf{\1}}$", chunk)
    chunk = re.sub(r"\\underline\{([^{}]*)\}", _underline_plain, chunk)
    chunk = _ENUMERATE_RE.sub(_render_enumerate, chunk)
    chunk = _MATH_ENV_RE.sub(_render_math_env, chunk)
    out = []
    for kind, *rest in _split_math(chunk):
        if kind == "math":
            inner, display = rest
            if display:
                out.append(_display_block(inner))
            else:
                out.append("$" + inner.replace("\\dfrac", "\\frac") + "$")
        else:
            out.append(_text_chunk_to_markdown(rest[0]))
    joined = "".join(out)
    # Single newlines in markdown are soft breaks (rendered as spaces).
    # In step-by-step solutions each source line is a logical step; promote
    # every single \n between non-empty content to a hard line break so that
    # each step renders on its own line.  Avoid touching newlines inside
    # fenced display-math blocks ($$...$$).
    parts = re.split(r"(\n\n\$\$\n.*?\n\$\$\n\n)", joined, flags=re.DOTALL)
    for idx in range(0, len(parts), 2):  # even indices are non-display text
        parts[idx] = re.sub(r"(?<=\S) *\n(?=\S)", "  \n", parts[idx])
    joined = "".join(parts)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def split_tex(tex: str, base_dir: str | Path) -> list[tuple[str, str]]:
    """Split tex into [("text", markdown), ("fig", abspath)] segments."""
    tex = _strip_comments(tex)
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


# ------------------------------------------------------ compiled-PNG fallback


@functools.lru_cache(maxsize=1)
def tex_engine_available() -> bool:
    """Probe once per process: can tectonic compile a trivial document?

    The first compile may download the package bundle, so the timeout is
    generous (a too-short probe would cache False until restart).
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "probe.tex"
            src.write_text(
                "\\documentclass{article}\\begin{document}hi\\end{document}\n"
            )
            r = subprocess.run(
                ["tectonic", "-o", tmp, str(src)],
                capture_output=True, text=True, timeout=180,
            )
            return r.returncode == 0 and (Path(tmp) / "probe.pdf").exists()
    except Exception:
        return False


# -------------------------------------------------------- tex line-break fix

# Patterns that mark a line as a LaTeX structural command (not content).
_STRUCT_LINE_RE = re.compile(
    r"^\s*\\(?:begin|end|documentclass|usepackage|pagestyle|includegraphics)\b"
)


def _add_tex_line_breaks(tex: str) -> str:
    """Insert ``\\\\`` between consecutive non-blank *content* lines.

    In the extracted fragments single newlines separate logical solution
    steps, but LaTeX treats them as whitespace.  This inserts explicit
    line breaks so the compiled PDF mirrors the source layout.  Lines
    that are blank, structural commands (``\\begin``, ``\\end``, …), or
    already end with ``\\\\`` are left untouched.
    """
    lines = tex.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        is_content = bool(stripped) and not _STRUCT_LINE_RE.match(stripped)
        already_has_break = stripped.endswith(r"\\")
        # Look ahead: next non-blank line
        next_content = False
        for j in range(i + 1, len(lines)):
            nxt = lines[j].strip()
            if nxt:
                next_content = not _STRUCT_LINE_RE.match(nxt)
                break
        if is_content and not already_has_break and next_content:
            out.append(stripped + r" \\")
        else:
            out.append(line)
    return "\n".join(out)


# Bump when the viewer wrapper changes: the PNG cache digest folds this in,
# so stale renders (old margins / page numbers / missing packages) recompile.
_WRAPPER_REV = "v5-linebreaks"

# Pixels of breathing room kept above/below content after the vertical trim.
_TRIM_PAD = 15


def _trim_vertical_whitespace(img):
    """Crop top/bottom all-white bands; keep full page width."""
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


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _pdf_to_image(pdf: Path):
    """Render EVERY page and stack them (normally one tall page; the stack is
    only a safety net so overlong content is never silently cut off)."""
    import fitz
    from PIL import Image

    d = fitz.open(str(pdf))
    try:
        pages = []
        for pg in d:
            pix = pg.get_pixmap(dpi=150)
            pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    finally:
        d.close()
    if len(pages) == 1:
        return pages[0]
    stacked = Image.new("RGB", (pages[0].width, sum(p.height for p in pages)), "white")
    y = 0
    for p in pages:
        stacked.paste(p, (0, y))
        y += p.height
    return stacked


def _write_err(path: Path, text: str) -> None:
    try:
        path.write_text(text[-3000:], encoding="utf-8")
    except OSError:
        pass


def render_error(work_dir: str | Path, out_name: str) -> str:
    """Last compile error for a render ("" if none): show it in the UI."""
    try:
        return (Path(work_dir) / (out_name + ".err")).read_text(encoding="utf-8")
    except OSError:
        return ""


def render_tex_to_png(tex: str, work_dir: str | Path, out_name: str) -> Path | None:
    """Compile a tex fragment to one tall PNG (article class only).

    Cached by content digest (tex + wrapper revision + figure bytes).
    Returns the PNG path, or None on failure; on failure the reason is
    written to <out_name>.err (see render_error).
    """
    if not tex_engine_available():
        return None
    work = Path(work_dir)
    out = work / out_name
    marker = work / (out_name + ".src_hash")
    err_file = work / (out_name + ".err")

    # Digest covers the tex, the wrapper revision, AND every referenced
    # figure's bytes: swapping a crop with identical tex must recompile.
    sha = hashlib.sha256((_WRAPPER_REV + "\n" + tex).encode())
    for m in INCLUDEGRAPHIC_RE.finditer(tex):
        sha.update(m.group("path").encode())
        sha.update(_fig_bytes_for_hash(work, m.group("path")))
    digest = sha.hexdigest()
    if out.exists() and marker.exists() and marker.read_text() == digest:
        return out

    # One tall page (40in) so long paragraph groups are never cut at a page
    # break; the vertical trim removes the unused space.
    tex_body = _add_tex_line_breaks(tex)
    doc = (
        "\\documentclass{article}\n"
        "\\usepackage[paperwidth=8.5in,paperheight=40in,margin=1in]{geometry}\n"
        "\\usepackage{amsmath,amssymb,graphicx,enumitem}\n"
        "\\begin{document}\n\\pagestyle{empty}\n\\small\n"
        + tex_body + "\n\\end{document}\n"
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            # Tectonic only reads files under the input file's directory,
            # so stage the wrapper .tex plus any referenced figures together.
            work_resolved = work.resolve()
            for m in INCLUDEGRAPHIC_RE.finditer(tex):
                fig = (work / m.group("path")).resolve()
                if fig.is_file():
                    rel = (fig.relative_to(work_resolved)
                           if _is_within(fig, work_resolved) else Path(fig.name))
                    dest = Path(tmp) / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(fig, dest)
            src = Path(tmp) / "view.tex"
            src.write_text(doc, encoding="utf-8")
            r = subprocess.run(
                ["tectonic", "-o", tmp, str(src)],
                capture_output=True, text=True, timeout=180, cwd=tmp,
            )
            pdf = Path(tmp) / "view.pdf"
            if r.returncode != 0 or not pdf.exists():
                tail = "\n".join((r.stderr or r.stdout or "").strip().splitlines()[-20:])
                _write_err(err_file, tail or "tectonic failed with no output")
                return None
            img = _trim_vertical_whitespace(_pdf_to_image(pdf))
            img.save(str(out), format="PNG")
        marker.write_text(digest)
        try:
            err_file.unlink()
        except OSError:
            pass
        return out
    except Exception as e:  # never raise into the UI
        _write_err(err_file, f"{type(e).__name__}: {e}")
        return None