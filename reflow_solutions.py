"""Deterministic solution-tex reflow: gaps without touching content.

Problem: agents often emit a solution body as ONE giant line; the renderer
turns line breaks into paragraphs, so the figure renders as a single wall
of math with no gaps. This module reflows the body deterministically (no
AI, no wording changes, math spans byte-identical):

1. Sentence split OUTSIDE math spans ($...$, $$...$$, \\[...\\]): split on
   `. `/`? `/`! ` (+ `) ` variants) before a capital/LaTeX-command,
   except after abbreviations (i.e., e.g., Fig., Eq., vs., etc., ...),
   single capitals handled by the same rule safely (they end sentences).
   Decimals ("3.25"), ellipsis labels ("...(i)") and "10-A" style tokens
   contain no `. `+capital, so they never split.
2. Native layout (matches agent-written files): text and equations never
   share a line (\\quad labels excepted). Long text runs get own lines;
   short text glues (parentheticals backward, lead-ins forward); symbol
   math ($C_1$, $^2$) always glues, never breaks; each equation starts a
   new line once the line holds one. Source delimiters are NEVER
   converted ($ stays $, $$ stays $$).
3. Blocks joined with single blank lines (existing blank-line structure
   in the header -- Answer/key/heading -- is preserved verbatim).

Idempotent: re-running yields byte-identical output (single sentences
don't re-split; display blocks are skipped as already-display).

Scope: one paper at a time via paper_id (never touches other papers).
Wire-in: `reflow_node` in graph.py runs it after `postprocess`.

Usage:
    python3 reflow_solutions.py <paper_id> [--outputs DIR] [--report-only]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_DISPLAY_MIN = 50  # inline math longer than this becomes display
_TEXT_SPLIT_MIN = 120  # text runs longer than this split at connectives
# a math span is an EQUATION (break-worthy) iff it states a relation;
# bare symbols ($C_1$, $^2$, $v_0$) always glue -- splitting "C_1 , C_1"
# or "A/m ^2" across lines is never correct, splitting equation chains
# ("v = ..", "integral ..", "= ..") always is.
_EQUATION_RES = ("=", "\\Rightarrow", "\\rightarrow", "\\approx",
                 "\\propto", "\\le", "\\geq", "\\neq", "\\sim", "<",
                 ">", "->", "⇒", "→", "≈")


def _is_equation(mtxt: str) -> bool:
    inner = mtxt[2:-2] if mtxt.startswith(("$$", "\\[")) else mtxt[1:-1]
    return any(op in inner for op in _EQUATION_RES)
_ABBREV = {"i.e", "e.g", "fig", "eq", "sec", "vs", "etc", "al", "no",
           "st", "ref", "approx", "resp", "viz"}
# discourse markers that start a new visual block when a text run has no
# sentence punctuation at all (agent wall-of-text). Splitting wrongly only
# adds a blank line -- harmless; missing a split leaves a wall.
_CONNECTIVES = (
    "Also,|Hence,|Hence|Therefore,|Therefore|Thus,|Let|Consider|Suppose|"
    "Now|Then|But|Since|From|Using|Putting|Substituting|Dividing|Adding|"
    "Similarly|Clearly|Obviously|For|In|Motion|Take|Differentiating|"
    "Integrating|When|Where|Here|There"
)


def _split_spans(text: str) -> list:
    """Split text into ("t", ...)/("m", ...) text/math spans.

    Handles $...$, $$...$$, \\[...\\]. Unclosed delimiters stay text
    (fail-safe: never reflows what it cannot parse).
    """
    spans = []
    i, n = 0, len(text)
    buf = ""
    while i < n:
        if text.startswith("$$", i):
            j = text.find("$$", i + 2)
            if j == -1:
                buf += text[i:]
                break
            if buf:
                spans.append(("t", buf))
                buf = ""
            spans.append(("m", text[i:j + 2], True))
            i = j + 2
        elif text.startswith("\\[", i):
            j = text.find("\\]", i + 2)
            if j == -1:
                buf += text[i:]
                break
            if buf:
                spans.append(("t", buf))
                buf = ""
            spans.append(("m", text[i:j + 2], True))
            i = j + 2
        elif text[i] == "$":
            j = text.find("$", i + 1)
            if j == -1:
                buf += text[i:]
                break
            if buf:
                spans.append(("t", buf))
                buf = ""
            spans.append(("m", text[i:j + 1], False))
            i = j + 1
        else:
            buf += text[i]
            i += 1
    if buf:
        spans.append(("t", buf))
    return spans


def _split_sentences(seg: str) -> list:
    """Split a math-free segment on sentence boundaries (keeps delimiters).

    Split after `.`/`?`/`!` (or after a closing paren ending one) + space,
    when followed by a capital letter or backslash, unless the token
    before the period is a known abbreviation.
    """
    parts, start = [], 0
    # find candidate ends: punctuation [.?!] optionally followed by )
    for m in re.finditer(r"[.!?]+\)?\s+(?=[A-Z\\])", seg):
        pre = seg[:m.start()].rstrip()
        tok = pre.split()[-1] if pre.split() else ""
        core = tok[:-1] if tok.endswith(")") else tok
        core = core.rstrip(".").lower()
        if core in _ABBREV or (len(core) == 1 and core.isalpha()
                               and not tok.endswith(")")):
            continue
        parts.append(seg[start:m.end()].strip())
        start = m.end()
    tail = seg[start:].strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def _mask(blk: str) -> tuple[str, list]:
    """Replace math spans with opaque tokens (sentence splitting and
    boundary scans must never see inside math)."""
    masked, maths = "", []
    for kind, *rest in _split_spans(blk):
        if kind == "t":
            masked += rest[0]
        else:
            masked += "\x00%d\x00" % len(maths)
            maths.append(rest[0])
    return masked, maths



def _glue(a: str, b: str) -> str:
    """Join two inline pieces: no space before closers/punctuation."""
    if not a:
        return b
    if not b:
        return a
    if b[:1] in ",.;:!?%)]}" or a[-1:] == "(":
        return a + b
    return a + " " + b


def reflow_solution_tex(text: str) -> tuple[str, dict]:
    """Reflow a solution.tex body. Returns (new_text, report)."""
    lines = text.split("\n")
    # header: Answer line, blank, Solution-for heading, blank -- verbatim
    head, body = lines[:4], lines[4:]
    # regroup body into paragraph blocks (blank-line separated)
    blocks, cur = [], []
    for ln in body:
        if ln.strip():
            cur.append(ln.strip())
        elif cur:
            blocks.append(" ".join(cur))
            cur = []
    if cur:
        blocks.append(" ".join(cur))
    out_blocks, n_sent, n_disp = [], 0, 0
    for blk in blocks:
        # mask math spans as opaque tokens so sentence splitting never
        # breaks inside them, then split the masked text into sentences
        masked, maths = _mask(blk)
        for sent in _split_sentences(masked):
            n_sent += 1
            # fallback: a long run with no sentence punctuation at all
            # (agent wall) splits at discourse connectives instead
            if (len(sent) > _TEXT_SPLIT_MIN
                    and not re.search(r"[.!?]\)?\s+[A-Z\\]", sent)):
                parts = re.split(r"\s+(?=(?:" + _CONNECTIVES + r")\b)",
                                  sent)
                subs = [p for p in (x.strip() for x in parts) if p]
                sents = subs if len(subs) > 1 else [sent]
            else:
                sents = [sent]
            for sent in sents:
                # restore math spans into runs: ("t", text) / ("m", tex, eq?)
                # operator-only spans (lone =>, =) ride the text logic so
                # they join their equation instead of standing alone
                runs = []
                for part in re.split("(\x00\\d+\x00)", sent):
                    m = re.fullmatch("\x00(\\d+)\x00", part)
                    if not m:
                        if part.strip():
                            runs.append(("t", part))
                        continue
                    mtxt = maths[int(m.group(1))]
                    inner = (mtxt[2:-2] if mtxt.startswith(("$$", "\\["))
                             else mtxt[1:-1])
                    # operator-only spans (lone =>, =, -) ride the text
                    # logic so they join their equation instead of
                    # standing alone; strip backslash-commands first so
                    # \Rightarrow / \rightarrow count as operators
                    if not re.search(r"[A-Za-z0-9]",
                                     re.sub(r"\\[a-zA-Z]+", "", inner)):
                        runs.append(("t", mtxt))
                    else:
                        runs.append(("m", mtxt, _is_equation(mtxt)))
                # native layout (matches agent-written files): text and
                # equations never share a line (\quad labels excepted).
                # - long text (>=15 chars): own line
                # - short text: parenthetical "(...)" glues backward; any
                #   other short text holds as pending for the next line
                #   (lead-ins join their equation; trailing units/labels
                #   fall back to the current line at sentence end)
                # - symbol math ($C_1$, $^2$): always glues, never breaks
                # - equation math: own line (source delimiters kept: $
                #   stays $, $$ stays $$); breaks the line iff the line
                #   already holds an equation
                # - display math ($$): own line, flushed around
                out = []
                buf = ""
                pending = ""
                for idx, run in enumerate(runs):
                    if run[0] == "t":
                        txt = re.sub(r"\s+", " ", run[1]).strip()
                        if not txt:
                            continue
                        # a clause joiner (leading , . ; : ! ? or ...)
                        # always rides backward -- a line must never
                        # start with one
                        if txt[:1] in ",.;:!?" or txt.startswith("..."):
                            buf = _glue(buf, txt)
                            continue
                        if len(txt) >= 15 or txt.startswith("("):
                            if pending:
                                txt = _glue(pending, txt).strip()
                                pending = ""
                            if buf.strip():
                                out.append(buf.strip())
                            buf = txt
                        elif pending:
                            pending = _glue(pending, txt).strip()
                        else:
                            # short text always holds as pending for the
                            # next line (unconditional forward): deciding
                            # by "math follows" breaks idempotency because
                            # re-blocked lines present different neighbor
                            # context; the sentence-end fallback below
                            # appends it back when nothing follows.
                            # Exception: bare punctuation (, . ;) belongs
                            # backward with the clause it ends -- a line
                            # must never start with a comma.
                            if re.fullmatch(r"[,.;:!?]+", txt):
                                buf = _glue(buf, txt)
                            else:
                                pending = txt
                        continue
                    _, mtxt, is_eq = run
                    is_disp = (mtxt.startswith("$$")
                               or mtxt.startswith("\\["))
                    if is_disp:
                        if pending:
                            buf = _glue(buf, pending)
                            pending = ""
                        if buf.strip():
                            out.append(buf.strip())
                            buf = ""
                        out.append(mtxt)
                        n_disp += 1
                        continue
                    if is_eq:
                        # every equation starts a fresh line; a pending
                        # lead-in ("Torque of ring", "For $v_x = 0$")
                        # joins its equation
                        if pending:
                            head_txt = pending
                            pending = ""
                        else:
                            head_txt = ""
                        if buf.strip():
                            out.append(buf.strip())
                        buf = _glue(head_txt, mtxt)
                        continue
                    if pending:
                        buf = _glue(buf, pending)
                        pending = ""
                    buf = _glue(buf, mtxt)
                if pending:
                    buf = _glue(buf, pending)
                if buf.strip():
                    out.append(buf.strip())
                out_blocks.extend(out)
    new = "\n".join(head) + "\n" + "\n\n".join(out_blocks) + "\n"
    before_lines = [len(l) for l in body if l.strip()]
    after_lines = [len(l) for l in out_blocks]
    return new, {"sentences": n_sent, "displayed": n_disp,
                 "maxlen_before": max(before_lines, default=0),
                 "maxlen_after": max(after_lines, default=0)}


def reflow_paper(paper_id: int, output_base=None,
                 report_only: bool = False) -> dict:
    """Reflow every solution.tex of one paper. Returns {file: report}."""
    if output_base is None:
        import directory_manager
        output_base = directory_manager.OUTPUT_BASE
    root = Path(output_base) / str(paper_id)
    out = {}
    for tex in sorted(root.glob("*/solution.tex")):
        original = tex.read_text()
        new, rep = reflow_solution_tex(original)
        rep["file"] = str(tex.parent.name) + "/solution.tex"
        rep["changed"] = new != original
        if rep["changed"] and not report_only:
            tex.write_text(new)
        out[str(tex)] = rep
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_id", type=int)
    ap.add_argument("--outputs", default=None)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()
    rep = reflow_paper(args.paper_id, args.outputs,
                       report_only=args.report_only)
    changed = sum(1 for r in rep.values() if r["changed"])
    print(f"{len(rep)} solutions: {changed} reflowed")
    for f, r in rep.items():
        if r["changed"]:
            print(f"  {r['file']}: {r['sentences']} sentences, "
                  f"{r['displayed']} display, maxlen "
                  f"{r['maxlen_before']}->{r['maxlen_after']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
