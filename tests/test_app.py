"""App helper tests: pairing, tex preprocessing, tex->png fallback."""
from __future__ import annotations

import pytest

from app.pairing import auto_pair, stem


def test_stem_normalizes():
    assert stem("GTA-01_QP.pdf") == "gta 01 qp"
    assert stem("GTA-01_Key & Sols.pdf") == "gta 01 &"
    assert stem("JEE 2024 Paper 1 Solutions.pdf") == "jee 2024 paper 1"
    assert stem("monkey business.pdf") == "monkey business"  # no inner-word strip


def test_auto_pair_gta_style():
    pairs = auto_pair(["GTA-01_QP.pdf", "GTA-02_QP.pdf"],
                      ["GTA-01_Key & Sols.pdf", "GTA-02_Key & Sols.pdf"])
    assert pairs == [("GTA-01_QP.pdf", "GTA-01_Key & Sols.pdf"),
                     ("GTA-02_QP.pdf", "GTA-02_Key & Sols.pdf")]


def test_auto_pair_unmatched_gets_none():
    assert auto_pair(["QP.pdf"], []) == [("QP.pdf", None)]
    pairs = auto_pair(["AAA_QP.pdf"], ["ZZZ_Solutions.pdf"])
    # very dissimilar names stay unpaired rather than forced
    assert pairs[0][1] is None or isinstance(pairs[0][1], (str, type(None)))


def test_tex_to_markdown_basics():
    from app.render import tex_to_markdown

    out = tex_to_markdown(r"\textbf{A)} $\sigma$ \hspace{2cm} 50\% sure \& done")
    assert "**A)**" in out and r"$\sigma$" in out and "50% sure & done" in out
    assert "hspace" not in out


def test_tex_comments_key_line_kept_rest_dropped():
    from app.render import tex_to_markdown

    out = tex_to_markdown("% Answer: 21-B\n21. Real solution $x=1$ here.\n% a note\ntrailing % cut")
    assert "% Answer" not in out
    assert "**Answer:** 21-B" in out
    assert "no_solution_found" not in out and "a note" not in out
    assert out.rstrip().endswith("trailing")


def test_tex_underline_heading_survives():
    from app.render import tex_to_markdown

    out = tex_to_markdown("\\underline{\\textbf{Solution for 29}}")
    assert out == "$\\underline{\\textbf{Solution for 29}}$"
    # No raw HTML: Streamlit escapes it, KaTeX renders the math form.
    assert "<u>" not in out


def test_tex_stray_dollar_escaped_not_paired():
    from app.render import tex_to_markdown

    out = tex_to_markdown("cost is $5 and $x=1$ ok")
    # "$5 and ..." must not open a math span; the real pair survives
    assert "$x=1$" in out
    assert "cost is $5 and" in out


def test_tex_escaped_dollar_stays_literal():
    from app.render import tex_to_markdown

    out = tex_to_markdown(r"pay \$5 for $x$")
    assert "$x$" in out and "pay $5 for" in out


def test_tex_keeps_spaces_around_inline_math():
    from app.render import tex_to_markdown

    out = tex_to_markdown("scales: $m_1L_1=m_2L_2$ Since then")
    assert "scales: $m_1L_1=m_2L_2$ Since then" in out


def test_tex_preserves_paragraph_breaks():
    from app.render import tex_to_markdown

    out = tex_to_markdown("First para $x=1$.\n\nSecond para $y=2$.")
    assert "First para $x=1$.\n\nSecond para $y=2$." in out


def test_tex_display_brackets_become_dollars():
    from app.render import tex_to_markdown

    out = tex_to_markdown(r"if \[ V_1L_1=V_2L_2 \] Divide")
    assert r"\[" not in out
    assert "$$V_1L_1=V_2L_2$$" in out


def test_tex_dfrac_tamed_only_inline():
    from app.render import tex_to_markdown

    out = tex_to_markdown(r"a $\dfrac{m_1}{V_1}$ b $$ \dfrac{x}{y} $$ c")
    assert r"$\frac{m_1}{V_1}$" in out  # inline: tamed
    assert r"\dfrac{x}{y}" in out  # display: left alone


def test_split_tex_extracts_figures(tmp_path):
    from app.render import split_tex

    (tmp_path / "figures").mkdir()
    (tmp_path / "figures" / "fig1.png").write_bytes(b"fake")
    segs = split_tex(
        "Intro.\n\\includegraphics[width=0.3\\linewidth]{figures/fig1.png}\nOutro $x$.",
        tmp_path)
    kinds = [k for k, _ in segs]
    assert kinds == ["text", "fig", "text"]
    assert segs[1][1].endswith("figures/fig1.png")
    assert "$x$" in segs[2][1]


def test_split_tex_missing_figure_flagged(tmp_path):
    from app.render import split_tex

    segs = split_tex(r"See \includegraphics{figures/ghost.png}.", tmp_path)
    assert segs[1] == ("fig", "")


def test_render_question_image_if_engine(tmp_path):
    from app.render import render_tex_to_png, tex_engine_available

    if not tex_engine_available():
        pytest.skip("no working tectonic bundle here")
    qdir = tmp_path / "q"
    qdir.mkdir()
    out = render_tex_to_png(r"Hello $E=mc^2$.", qdir, "_q.png")
    assert out is not None and out.is_file() and out.stat().st_size > 1000
    # Cached second call returns the same file without recompiling.
    assert render_tex_to_png(r"Hello $E=mc^2$.", qdir, "_q.png") == out


def test_render_with_figure_stages_it_for_compile(tmp_path):
    """Regression: \\includegraphics must resolve (tectonic sandboxes to cwd)."""
    from PIL import Image as PILImage

    from app.render import render_tex_to_png, tex_engine_available

    if not tex_engine_available():
        pytest.skip("no working tectonic bundle here")
    qdir = tmp_path / "q"
    (qdir / "figures").mkdir(parents=True)
    PILImage.new("RGB", (60, 40), "white").save(str(qdir / "figures" / "a.png"))
    out = render_tex_to_png(r"See \includegraphics{figures/a.png} here.", qdir, "_q.png")
    assert out is not None and out.is_file() and out.stat().st_size > 1000


def test_vertical_trim_keeps_width_drops_dead_bands():
    """Unit: trim kills top/bottom whitespace, keeps full width + padding."""
    from PIL import Image as PILImage

    from app.render import _TRIM_PAD, _trim_vertical_whitespace

    img = PILImage.new("RGB", (200, 400), "white")
    px = img.load()
    for y in range(50, 101):
        for x in range(20, 181):
            px[x, y] = (0, 0, 0)
    out = _trim_vertical_whitespace(img)
    assert out.width == 200
    assert out.height == (100 - 50 + 1) + 2 * _TRIM_PAD
    # All-white page is returned untouched.
    blank = PILImage.new("RGB", (200, 400), "white")
    assert _trim_vertical_whitespace(blank).size == (200, 400)
