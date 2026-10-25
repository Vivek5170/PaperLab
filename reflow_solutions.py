"""Deterministic solution-tex reflow: gaps without touching content.

Problem: agents often emit a solution body as ONE giant line; the renderer
turns line breaks into paragraphs, so the figure renders as a single wall
of math with no gaps. This module reflows the body deterministically (no
AI, no wording changes, math spans byte-identical):

1. Sentence split OUTSIDE math spans ($...$, $$...$$, \\[...\\]): split on
   `. `/`? `/`! ` (+ `) ` variants) before a capital/LaTeX-command,
   except after abbreviations (i.e., e.g., Fig., Eq., vs., etc., ...),
   single capitals handled by the same rule safely (they end sentences).
   Decimals ("3.25") and "10-A" style tokens contain no `. `+capital,
   so they never split. Ellipsis/equation labels ("...(i)", "(2)") DO
   split when a new sentence follows them ("...(iv) Solving"): the mask
   token or "..." before the label proves it tails an equation, while a
   leading "(1)" list number has neither and is left alone. A comma
   after ")" ("(iv), we get") means continuation, never a split.
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
# a math span is an EQUATION (break-worthy) iff it states a relation
# (=, =>-family, approx/propto/le/ge/neq/sim). Comparison and definition
# fragments ($> \sigma$, $\sigma_f \rightarrow$, $C_1$, $^2$) always glue
# inline -- splitting "=> sigma / at point X > sigma" or "Let sigma_f -> /
# charge density ..." across lines shreds the clause (the A-02 lesson).
# bare >, <, ->, ->-family never break a line on their own.
_EQUATION_RES = ("=", "\\Rightarrow", "\\Longrightarrow", "\\approx",
                 "\\propto", "\\le", "\\geq", "\\neq", "\\sim",
                 "\\simeq", "\\equiv", "⇒", "≈")
# fragments comparing or defining (no relation marker): glue inline, but a
# completed long-text tail closes the line for them (next definition starts
# fresh) while subscript/superscript/unit symbols always ride along.
_FRAGMENT_RES = (">", "<", "\\rightarrow", "\\to", "→")
# words that always start a fresh clause: never appended to the current
# line, always held as pending for what follows (head of the next
# equation/fragment or start of a new line).
_CLAUSE_STARTERS = ("Also", "Let", "Suppose", "Assume", "Put",
                    "Consider", "Define", "Denote")
# lone joiners never end a line: held as pending so they head the next
# math ("and $rho_s = ...") instead of dangling ("... $^3$ and").
# Only exact runs -- never split inside longer text (no churn).
_JOINERS = ("and", "or", "And", "Or")


def _is_equation(mtxt: str) -> bool:
    inner = mtxt[2:-2] if mtxt.startswith(("$$", "\\[")) else mtxt[1:-1]
    return any(op in inner for op in _EQUATION_RES)


def _is_fragment(mtxt: str) -> bool:
    """A math span with comparison/definition markers but no relation."""
    inner = mtxt[2:-2] if mtxt.startswith(("$$", "\\[")) else mtxt[1:-1]
    if _is_equation(mtxt):
        return False
    return any(op in inner for op in _FRAGMENT_RES)


def _is_operator_text(txt: str) -> bool:
    """Bare operators (lone =>, =, -, ∴) ride text logic, never append."""
    t = txt.strip()
    if re.fullmatch(r"[⇒∴∵→←↔=+\-*/<>×÷±∓⋅∘]+", t):
        return True
    m = re.fullmatch(r"\$(.*)\$", t, re.DOTALL)
    if m and not re.search(r"[A-Za-z0-9]",
                           re.sub(r"\\[a-zA-Z]+", "", m.group(1))):
        return True
    return False


def _is_clause_starter(txt: str) -> bool:
    """Also,/Let/... start a fresh clause -- never append to a line."""
    return txt.strip().rstrip(",") in _CLAUSE_STARTERS


def _is_joiner(txt: str) -> bool:
    """A lone and/or heads what follows -- never dangles at line end."""
    return txt.strip().rstrip(",") in _JOINERS


def _split_clauses(part: str) -> list:
    """Split a text part before clause starters (Also, Let, ...).

    "...(i) Also, ..." must not glue backward as one run: the "...(i)"
    label stays with its equation while "Also," heads the next one.
    """
    return [p for p in re.split(
        r"\s+(?=(?:" + "|".join(_CLAUSE_STARTERS) + r")\b)", part) if p]
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


# an equation label closing a derivation step never shares its line
# with the next sentence ("...(iv) Solving", "(2) From"). A math mask
# token directly before the label (optionally via "...", spacing
# irrelevant -- pass one normalizes it, so the rule must fire on both
# shapes or idempotency breaks) proves it tails an equation: a leading
# "(1)" list number and a clause-leader like "Let ...(i)" have a word
# (not math) before the dots and can never match. A comma after ")"
# ("(iv), we get") means continuation, never a split.
_LABEL_SPLIT_RE = re.compile(
    r"\x00\d+\x00\s*(?:\.\.\.\s*)?"
    r"\((?:[ivxlcdm]+|\d+)\)\s+(?=[A-Z])")


def _split_sentences(seg: str) -> list:
    """Split a math-free segment on sentence boundaries (keeps delimiters).

    Split after `.`/`?`/`!` (or after a closing paren ending one) + space,
    when followed by a capital letter or backslash, unless the token
    before the period is a known abbreviation. Also split after an
    equation label (`...(iv)`, `(2)`) when a new sentence follows it.
    """
    cuts = []

    def _period_end(m):
        pre = seg[:m.start()].rstrip()
        toks = pre.split()
        tok = toks[-1] if toks else ""
        core = tok[:-1] if tok.endswith(")") else tok
        core = core.rstrip(".").lower()
        if core in _ABBREV or (len(core) == 1 and core.isalpha()
                               and not tok.endswith(")")):
            # ... but a lone letter after a math span is a unit glued to
            # its quantity ("$\76^{\circ}$ C. During ..."), not an
            # initial ("J. Smith"): the mask token before it proves the
            # math attachment, so the boundary stands. (Without this,
            # _glue's inserted space flips the tokenization between runs
            # and breaks idempotency.)
            if not (len(toks) >= 2
                    and re.fullmatch("\x00\\d+\x00", toks[-2])):
                return None
        return m.end()

    # find candidate ends: punctuation [.?!] optionally followed by )
    for m in re.finditer(r"[.!?]+\)?\s+(?=[A-Z\\])", seg):
        end = _period_end(m)
        if end is not None:
            cuts.append(end)
    # ... plus equation-label ends. No position guard is needed: every
    # match proves math directly before the label, which a leading list
    # number never has. But the follower must be able to stand alone:
    # a short math-less fragment ("In air gap,") would strand as an
    # orphan line, so only split when the following sentence runs long
    # or carries math (same 15-char line as the layout engine).
    for m in _LABEL_SPLIT_RE.finditer(seg):
        rest = seg[m.end():]
        nxt = re.search(r"[.!?]", rest)
        span = rest[:nxt.start()] if nxt else rest
        if (re.search(r"\x00\d+\x00", span)
                or len(re.sub(r"\x00\d+\x00", " ", span).strip()) >= 15):
            cuts.append(m.end())
    parts = []
    prev = 0
    for cut in sorted(set(cuts)):
        if cut > prev:
            parts.append(seg[prev:cut].strip())
            prev = cut
    tail = seg[prev:].strip()
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


def _is_structural(block: str) -> bool:
    """Lines that must always stand alone: figures, environments, answer
    and section headers. A shred seam is never healed across these."""
    s = block.strip()
    if ("\\includegraphics" in s or "\\begin{" in s or "\\end{" in s):
        return True
    if re.match(r"\\(textbf|underline)", s):
        return True
    return False


_ITEM_START_RE = re.compile(r"\([A-Za-z0-9]+\)|\d+\.")


def _hard_boundary(prev: str, nxt: str) -> bool:
    """True iff two adjacent blocks must stay separate: either side is
    structural, or the next block starts a list/option item."""
    if _is_structural(prev) or _is_structural(nxt):
        return True
    if _ITEM_START_RE.match(nxt.strip()):
        return True
    return False


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
    # heal pass: rejoin shred seams so the handler is independent of the
    # input shape -- walls, agent line-breaks, or already-shredded lines
    # all canonicalize to the same layout. Structural blocks (figures,
    # environments, headers) and list/option starts never merge.
    healed = []
    for blk in blocks:
        if healed and not _hard_boundary(healed[-1], blk):
            healed[-1] = healed[-1] + " " + blk
        else:
            healed.append(blk)
    blocks = healed
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
                if len(subs) > 1:
                    # a short lead-in stranded without math ("In air
                    # gap," split off the tail) would orphan: fold
                    # short math-less pieces into the next piece so
                    # they head what follows; a trailing one rides
                    # the previous piece
                    merged, carry = [], ""
                    for sub in subs:
                        if (len(sub) < 15
                                and not re.search("\x00\\d+\x00", sub)):
                            carry = (carry + " " + sub).strip()
                            continue
                        if carry:
                            sub = (carry + " " + sub).strip()
                            carry = ""
                        merged.append(sub)
                    if carry and merged:
                        merged[-1] = (merged[-1] + " " + carry).strip()
                    elif carry:
                        merged.append(carry)
                    subs = merged
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
                        for clause in _split_clauses(part):
                            if clause.strip():
                                runs.append(("t", clause))
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
                # native layout (matches the source solution books): a real
                # equation (=, =>-family) breaks the line; comparison and
                # definition fragments (>, ->, subscripts, units) glue
                # inline so clauses are never shredded ("=> sigma / at
                # point X > sigma" stays one line; "Let sigma_f ->
                # charge ..." stays one line; "...(i)" labels stay with
                # their equation while "Also," heads the next one).
                # - long text (>=15 chars): joins a line still being
                #   built, else flushes a completed (=) line and starts
                #   a fresh one
                # - short text: operators (=>, ∴) and clause starters
                #   (Also, Let, ...) always hold as pending; other short
                #   text appends to the open line, else holds as pending
                # - equation math: own line (source delimiters kept: $
                #   stays $, $$ stays $$); a pending lead-in joins it
                # - fragment math: appends to the open line (a completed
                #   long-text tail closes the line for comparisons, but
                #   never for subscript/unit symbols); a pending head
                #   ("Let", "or") starts it as a fresh line
                # - display math ($$): own line, flushed around
                out = []
                buf = ""
                pending = ""
                long_tail = False
                frag_tail = False
                for idx, run in enumerate(runs):
                    if run[0] == "t":
                        txt = re.sub(r"\s+", " ", run[1]).strip()
                        if not txt:
                            continue
                        # a clause joiner (leading , . ; : ! ? or ...)
                        # always rides backward -- a line must never
                        # start with one. A dangling pending folds into
                        # the line first, else the joiner would overtake
                        # it and flip line order between runs. With
                        # nothing behind it (leading "...(i)"), it waits
                        # as pending for its line instead of orphaning.
                        if txt[:1] in ",.;:!?" or txt.startswith("..."):
                            if pending or buf.strip():
                                if pending:
                                    buf = _glue(buf, pending)
                                    pending = ""
                                buf = _glue(buf, txt)
                            else:
                                pending = txt
                            continue
                        if len(txt) >= 15 or txt.startswith("("):
                            if pending:
                                txt = _glue(pending, txt).strip()
                                pending = ""
                            if "=" in buf:
                                # completed equation line: flush, fresh line
                                if buf.strip():
                                    out.append(buf.strip())
                                buf = txt
                                frag_tail = False
                            else:
                                # line still being built (definition tail,
                                # open derivation step): complete it here
                                buf = _glue(buf, txt)
                            long_tail = True
                        elif pending:
                            pending = _glue(pending, txt).strip()
                        elif _is_operator_text(txt):
                            # a bare operator continues the open step
                            # ("at point X $>$ ...") but starts a new one
                            # after a completed equation (Q7's "=>" after
                            # "$V_2 = ...$") or on an empty line
                            if buf.strip() and "=" not in buf:
                                buf = _glue(buf, txt)
                            else:
                                pending = txt
                        elif (_is_clause_starter(txt)
                                or _is_joiner(txt)):
                            # starters open a fresh clause; joiners head
                            # what follows -- never append to the line
                            pending = txt
                        elif re.fullmatch(r"[,.;:!?]+", txt):
                            if pending or buf.strip():
                                if pending:
                                    buf = _glue(buf, pending)
                                    pending = ""
                                buf = _glue(buf, txt)
                            else:
                                pending = txt
                        elif buf.strip():
                            # continuation of the open clause ("at point
                            # X", "A/m") rides the current line
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
                        long_tail = False
                        frag_tail = False
                        n_disp += 1
                        continue
                    if is_eq:
                        # every equation starts a fresh line; a pending
                        # lead-in ("Torque of ring", "Also,") joins it
                        if pending:
                            head_txt = pending
                            pending = ""
                        else:
                            head_txt = ""
                        if buf.strip():
                            out.append(buf.strip())
                        buf = _glue(head_txt, mtxt)
                        long_tail = ("=" in mtxt)
                        frag_tail = False
                        continue
                    if pending:
                        # definition head ("Let", "or"): fresh line
                        if buf.strip():
                            out.append(buf.strip())
                        buf = _glue(pending, mtxt)
                        pending = ""
                        long_tail = False
                        frag_tail = _is_fragment(mtxt)
                        continue
                    if (buf.strip() and long_tail and frag_tail
                            and _is_fragment(mtxt)):
                        # a completed definition tail closes the line
                        # ("... charge ... at X" then "sigma_i ->"
                        # starts fresh); a clause whose math hasn't
                        # started yet ("Further, field for " then
                        # "$r > a$") keeps building, and subscript or
                        # unit symbols always ride along
                        out.append(buf.strip())
                        buf = mtxt
                        long_tail = False
                        frag_tail = True
                    else:
                        buf = _glue(buf, mtxt)
                        if _is_fragment(mtxt):
                            frag_tail = True
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
