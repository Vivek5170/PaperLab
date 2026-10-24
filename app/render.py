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


# Inline options: legacy questions put all options on ONE source line
# ("\textbf{A)} ... \hspace{1cm} \textbf{B)} ..."). Markdown would render
# that as a single wrapped paragraph. Split each option label onto its own
# paragraph so every option starts on a new line. Only triggers when 2+
# option labels share a text chunk (enumerate environments are handled
# separately); math chunks never reach this function.
_OPTION_LABEL_RE = re.compile(r"\\textbf\{([B-D])\)\}")
_OPTION_COUNT_RE = re.compile(r"\\textbf\{[A-D]\)\}")


def _split_inline_options(s: str) -> str:
    """One paragraph per option when options share a single source line."""
    if len(_OPTION_COUNT_RE.findall(s)) < 2:
        return s
    # Drop the inter-option spacing commands; the paragraph break replaces them.
    s = re.sub(r"\\(?:hspace|vspace)\{[^}]*\}(?=\s*\\textbf\{[A-D]\)\})", "", s)
    s = _OPTION_LABEL_RE.sub(r"\n\n\\textbf{\1)}", s)
    # A) is first: when glued to the stem ("...then :-\n\textbf{A)}") it
    # would keep sharing the stem's line (single \n = soft break). Promote
    # it to its own paragraph. Already-separated A) (blank line / start of
    # string) can't match: \n is not in the gap class, so \n\n never matches.
    s = re.sub(r"(\S)[ \t]*\n?[ \t]*\\textbf\{A\)\}", r"\1\n\n\\textbf{A)}", s)
    # Idempotent: re-saving already-split tex must not stack blank lines.
    return re.sub(r"\n{3,}", "\n\n", s)


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
        # Agents sometimes write "\item A) 4": the counter already supplies
        # the label, so strip a redundant leading one ("A)", "(A)", "A.").
        part = re.sub(r"^\s*\(?[A-D]\)?[).]\s+", "", part.strip())
        out.append("\n\n" + marker + part)
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


# ------------------------------------------------- tabular environments

_TAB_BEGIN_RE = re.compile(r"\\begin\{tabular\}")
_TAB_END_RE = re.compile(r"\\end\{tabular\}")
_FIG_CMD_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]+\}")
_ROW_SPLIT_RE = re.compile(r"\\\\(?:\[[^\]]*\])?")


def _balanced_braces(s: str, i: int) -> tuple[str, int] | None:
    """Read `{...}` starting at s[i]; return (inner, index-after-close)."""
    if i >= len(s) or s[i] != "{":
        return None
    depth, j = 0, i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return None


def _strip_multicolumn(body: str) -> str:
    """\\multicolumn{n}{spec}{text} -> text (balanced-brace safe)."""
    out, i = [], 0
    while True:
        m = body.find("\\multicolumn", i)
        if m == -1:
            out.append(body[i:])
            return "".join(out)
        out.append(body[i:m])
        j = m + len("\\multicolumn")
        args = []
        for _ in range(3):
            b = _balanced_braces(body, j)
            if b is None:
                break
            args.append(b)
            j = b[1]
        if len(args) != 3:
            out.append(body[m:j])  # malformed: leave untouched
        else:
            out.append(args[2][0])
        i = j


def _split_tabular_rows(body: str) -> list[list[str]]:
    """Split a tabular body into rows of raw cell strings."""
    rows: list[list[str]] = []
    for raw in _ROW_SPLIT_RE.split(body):
        cells = [c.strip() for c in raw.replace(r"\&", "\x00AMP\x00").split("&")]
        cells = [c.replace("\x00AMP\x00", "\\&") for c in cells]
        if not any(c.strip(" \n\t|") for c in cells):
            continue
        rows.append(cells)
    return rows


# Center-wrapped figure + caption inside a cell: the \\ after the figure is
# a caption break, NOT a row separator. Consume it with the figure so row
# splitting doesn't orphan the caption into a bogus row.
_CENTER_FIG_RE = re.compile(
    r"\\begin\{center\}\s*(\\includegraphics(?:\[[^\]]*\])?\{[^}]+\})"
    r"\s*(?:\\\\(?:\[[^\]]*\])?)?\s*([\s\S]*?)\\end\{center\}")


def _prep_tabular_body(body: str) -> tuple[str, list[str]]:
    """Hoist figures, drop rules, unwrap multicolumns; return (body, figs)."""
    figs: list[str] = []

    def _take_center(m: "re.Match") -> str:
        figs.append(m.group(1))
        return " " + m.group(2).strip() + " "

    body = _CENTER_FIG_RE.sub(_take_center, body)
    figs.extend(_FIG_CMD_RE.findall(body))
    body = _FIG_CMD_RE.sub("", body)
    body = re.sub(r"\\hline|\\cline\{[^}]*\}", "", body)
    return _strip_multicolumn(body), figs


def _render_one_tabular(body: str) -> str:
    """Top-level tabular body -> markdown table + hoisted figs.

    Figures can't live inside markdown table cells (split_tex would cut the
    table mid-row to display them), so \\includegraphics commands are moved
    below the table; split_tex then yields [table, fig, ...] segments.
    """
    body, figs = _prep_tabular_body(body)
    rows = _split_tabular_rows(body)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    def cell(c: str) -> str:
        # A cell is one line: no raw row breaks or newlines may survive.
        return tex_to_markdown(c).replace("\\\\", " ").replace("\n", " ").strip()

    md = ["| " + " | ".join(cell(c) for c in rows[0]) + " |",
          "| " + " | ".join("---" for _ in rows[0]) + " |"]
    for r in rows[1:]:
        md.append("| " + " | ".join(cell(c) for c in r) + " |")
    if figs:
        md.append("")
        md.extend(figs)
    return "\n".join(md)


def _flatten_one_tabular(body: str) -> str:
    """Nested tabular body -> plain flowing text (cells joined by spaces)."""
    body, figs = _prep_tabular_body(body)
    parts = []
    for r in _split_tabular_rows(body):
        parts.extend(tex_to_markdown(c).replace("\\\\", " ").replace("\n", " ").strip()
                     for c in r)
    # Kept inline so an enclosing figure-table still finds them as cells.
    parts.extend(figs)
    return " ".join(p for p in parts if p)


# Placeholder for a hoisted figure inside a parsed table cell.
_TFIG_RE = re.compile(r"@@TFIG:(\d+)@@")
_MTABLE_RE = re.compile(r"@@MTABLE:(\d+)@@")


def _parse_table_cells(body: str) -> tuple[list[list[str]], list[str]]:
    """Split a tabular body into raw cells, figures as @@TFIG:n@@ markers.

    Returns (rows, fig_cmds). Center-wrapped figure+caption keeps the caption
    glued in the cell; the caption-break \\\\ is consumed so it never splits
    the row. Nested tabulars are flattened by the caller beforehand.
    """
    figs: list[str] = []

    def _take_center(m: "re.Match") -> str:
        figs.append(m.group(1))
        return " @@TFIG:%d@@ %s " % (len(figs) - 1, m.group(2).strip())

    def _take_fig(m: "re.Match") -> str:
        figs.append(m.group(0))
        return " @@TFIG:%d@@ " % (len(figs) - 1)

    body = _CENTER_FIG_RE.sub(_take_center, body)
    body = _FIG_CMD_RE.sub(_take_fig, body)
    body = re.sub(r"\\hline|\\cline\{[^}]*\}", "", body)
    body = _strip_multicolumn(body)
    return _split_tabular_rows(body), figs


def _cell_items(raw: str, figs: list[str]):
    """Raw cell -> [("text", md)] / [("fig", cmd), ("text", md)] items."""
    items: list[tuple[str, str]] = []
    pos = 0
    for m in _TFIG_RE.finditer(raw):
        txt = raw[pos:m.start()].strip()
        if txt:
            txt = tex_to_markdown(txt).replace("\\\\", " ").replace("\n", " ").strip()
            if txt:
                items.append(("text", txt))
        items.append(("fig", figs[int(m.group(1))]))
        pos = m.end()
    txt = raw[pos:].strip()
    if txt:
        txt = tex_to_markdown(txt).replace("\\\\", " ").replace("\n", " ").strip()
        if txt:
            items.append(("text", txt))
    return items or [("text", "")]


def _build_table(body: str) -> dict:
    """Top-level tabular body -> {"header", "rows"} with fig cells inline."""
    rows_raw, figs = _parse_table_cells(body)
    if not rows_raw:
        return {"header": [], "rows": []}
    width = max(len(r) for r in rows_raw)
    rows_raw = [r + [""] * (width - len(r)) for r in rows_raw]
    table = {"header": [_cell_items(c, figs) for c in rows_raw[0]], "rows": []}
    for r in rows_raw[1:]:
        table["rows"].append([_cell_items(c, figs) for c in r])
    return table


def _render_tabulars(chunk: str, tables: list | None = None) -> str:
    """Replace every tabular env: nested ones flatten, top-level tabulate.

    When `tables` is given, a top-level tabular containing figures becomes
    a {"header", "rows"} object (figures inline as cells) referenced by an
    @@MTABLE:n@@ placeholder; otherwise (plain tex_to_markdown path) the
    legacy behavior holds: markdown table with figures hoisted below.
    """
    while True:
        begins = list(_TAB_BEGIN_RE.finditer(chunk))
        if not begins:
            return chunk
        b = begins[-1]  # deepest: no other opener between it and its closer
        spec = _balanced_braces(chunk, b.end())
        if spec is None:
            return chunk
        _, body_start = spec
        m = _TAB_END_RE.search(chunk, body_start)
        if m is None:
            return chunk  # unbalanced: leave untouched, never corrupt
        # Nested if another opener is still open here (no closer before it).
        depth = (len(_TAB_BEGIN_RE.findall(chunk, 0, b.start()))
                 - len(_TAB_END_RE.findall(chunk, 0, b.start())))
        body = chunk[body_start:m.start()]
        if depth > 0:
            repl = _flatten_one_tabular(body)
        elif tables is not None and _FIG_CMD_RE.search(body):
            tables.append(_build_table(body))
            repl = "@@MTABLE:%d@@" % (len(tables) - 1)
        else:
            repl = _render_one_tabular(body)
        chunk = chunk[:b.start()] + "\n\n" + repl + "\n\n" + chunk[m.end():]


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
    # Legacy inline options live on one source line, so the math splitter
    # would isolate each label in its own text chunk. Split here instead,
    # while labels are still visible together (enumerate already handled).
    chunk = _split_inline_options(chunk)
    # Match-table environments (List-I / List-II). Must run before math
    # splitting: & and \\\\ are cell/row structure here, not text.
    chunk = _render_tabulars(chunk)
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
    # Paragraph breaks come from the stored tex itself (normalize_steps
    # inserts a blank line between steps at save time), so no promotion of
    # single newlines here: a single \n is a space in both LaTeX and
    # markdown, and forcing hard breaks would split hard-wrapped prose.
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


_SPLIT_RE = re.compile(
    r"(\\includegraphics(?:\[[^\]]*\])?\{[^}]+\})|(@@MTABLE:\d+@@)")


def _resolve_fig(base: Path, rel: str) -> str:
    fig = (base / rel).resolve()
    return str(fig) if fig.is_file() else ""


def _resolve_table(base: Path, table: dict) -> dict:
    """Turn figure commands into abspaths; missing files become text notes."""
    def _cell(items):
        out = []
        for kind, val in items:
            if kind == "fig":
                m = INCLUDEGRAPHIC_RE.search(val)
                rel = m.group("path") if m else val
                abspath = _resolve_fig(base, rel)
                out.append(("fig", abspath) if abspath
                           else ("text", "(figure missing: %s)" % rel))
            else:
                out.append((kind, val))
        return out or [("text", "")]
    return {"header": [_cell(c) for c in table["header"]],
            "rows": [[_cell(c) for c in r] for r in table["rows"]]}


def split_tex(tex: str, base_dir: str | Path):
    """Split tex into segments: ("text", markdown), ("fig", abspath) or
    ("table", {"header", "rows"}) with figures inline as cells."""
    tex = _strip_comments(tex)
    # Tables first, on the whole tex: a table with figures becomes one
    # ("table", ...) segment instead of being cut mid-row. Splitting on
    # figures first would shred tables into unparseable halves.
    tables: list = []
    tex = _render_tabulars(tex, tables=tables)
    base = Path(base_dir)
    segments: list = []
    pos = 0
    for m in _SPLIT_RE.finditer(tex):
        before = tex[pos:m.start()].strip()
        if before:
            segments.append(("text", tex_to_markdown(before)))
        if m.group(2) is not None:
            segments.append(("table", _resolve_table(
                base, tables[int(_MTABLE_RE.match(m.group(2)).group(1))])))
        else:
            segments.append(("fig", _resolve_fig(
                base, INCLUDEGRAPHIC_RE.match(m.group(1)).group("path"))))
        pos = m.end()
    tail = tex[pos:].strip()
    if tail:
        segments.append(("text", tex_to_markdown(tail)))
    return segments


# Bump when the full-paper builder changes: the app's cache key folds this
# in, so old bytes are never served after a builder fix (same tex, new code).
_FULLPDF_REV = "v2-figpaths"

# Matches \includegraphics[opts]{figures/...} so the figures/ prefix can be
# retargeted at a staged per-item directory (keeps the [opts] intact).
_FIG_REWRITE_RE = re.compile(
    r"\\includegraphics(?P<opts>\[[^\]]*\])?\{figures/(?P<path>[^}]+)\}")


# ------------------------------------------------- full-paper PDF download

_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_ESCAPE_RE = re.compile(r"[\\&%$#_{}~^]")


def _escape_latex(s: str) -> str:
    """Escape one pass (chained replace would corrupt inserted commands)."""
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_ESCAPES[m.group(0)], s)


def build_paper_pdf(items: list[tuple[str, str, str, "Path | None"]],
                    title: str) -> bytes | None:
    """Compile a full paper PDF: question + key + solution per item.

    ``items`` is [(question_number, question_tex, solution_tex, figures_dir)]
    in display order; the solution's own first line is its key. Items are
    separated by a horizontal rule. Figure paths (figures/...) are staged
    per item and rewritten. Returns PDF bytes, None on failure; never
    raises.
    """
    if not tex_engine_available():
        return None
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            parts = [
                "\\documentclass{article}\n"
                "\\usepackage[paperwidth=8.5in,paperheight=11in,margin=1in]{geometry}\n"
                "\\usepackage{amsmath,amssymb,graphicx,enumitem}\n"
                "\\setlength{\\parindent}{0pt}\\setlength{\\parskip}{6pt}\n"
                + _FIG_CAP_PREAMBLE +
                "\\begin{document}\n\\pagestyle{empty}\n"
                "{\\large\\textbf{" + _escape_latex(title) + "}}\n"
            ]
            for idx, (qn, qtex, stex, figdir) in enumerate(items):
                tag = f"q{idx}"
                if figdir is not None and Path(figdir).is_dir():
                    dest = tmp / tag
                    shutil.copytree(figdir, dest, dirs_exist_ok=True)

                def _stage(m: "re.Match") -> str:
                    return (r"\includegraphics" + (m.group("opts") or "")
                            + "{" + tag + "/" + m.group("path") + "}")

                qtex = _FIG_REWRITE_RE.sub(_stage, qtex or "")
                stex = _FIG_REWRITE_RE.sub(_stage, stex or "")
                if idx:
                    parts.append("\n\\noindent\\rule{\\linewidth}{0.5pt}\n")
                parts.append("\n\\textbf{Question "
                             + _escape_latex(str(qn)) + "}\n\n"
                             + qtex + "\n\n" + stex + "\n")
            parts.append("\\end{document}\n")
            src = tmp / "paper.tex"
            src.write_text("".join(parts), encoding="utf-8")
            r = subprocess.run(
                ["tectonic", "-o", tmp, str(src)],
                capture_output=True, text=True, timeout=300, cwd=tmp,
            )
            pdf = tmp / "paper.pdf"
            if r.returncode == 0 and pdf.is_file():
                return pdf.read_bytes()
    except Exception:
        pass
    return None


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


# Bump when the viewer wrapper changes: the PNG cache digest folds this in,
# so stale renders (old margins / page numbers / missing packages) recompile.
_WRAPPER_REV = "v7-figcap"

# Widest a figure may render in the compiled PNG, as a fraction of the text
# width. Crops are full-page-width rasters, so authored widths like
# 0.9\linewidth blow them up; caps shrink the oversized ones while figures
# already under the cap pass through untouched (never enlarged).
_FIG_MAX_WIDTH = r"0.65\linewidth"

_FIG_CAP_PREAMBLE = (
    "\\makeatletter\n"
    "\\newsavebox{\\PL@figbox}\n"
    "\\let\\PL@includegraphics\\includegraphics\n"
    "\\renewcommand{\\includegraphics}[2][]{%\n"
    "  \\sbox{\\PL@figbox}{\\PL@includegraphics[#1]{#2}}%\n"
    "  \\ifdim\\wd\\PL@figbox>" + _FIG_MAX_WIDTH + "\n"
    "    \\resizebox{" + _FIG_MAX_WIDTH + "}{!}{\\usebox{\\PL@figbox}}%\n"
    "  \\else\n"
    "    \\usebox{\\PL@figbox}%\n"
    "  \\fi}\n"
    "\\makeatother\n"
)

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
    # break; the vertical trim removes the unused space. Paragraph breaks
    # come from the stored tex (normalize_steps at save time); zero indent
    # plus vertical space keeps steps visually separate without indentation.
    tex_body = tex
    doc = (
        "\\documentclass{article}\n"
        "\\usepackage[paperwidth=8.5in,paperheight=40in,margin=1in]{geometry}\n"
        "\\usepackage{amsmath,amssymb,graphicx,enumitem}\n"
        "\\setlength{\\parindent}{0pt}\\setlength{\\parskip}{6pt}\n"
        + _FIG_CAP_PREAMBLE +
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