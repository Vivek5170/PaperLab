/**
 * MOCK ONLY (exp/tex-editor): representative sample TeX and a tiny
 * client-side TeX -> HTML renderer so the experimental workspace can
 * demonstrate live preview with zero backend involvement.
 *
 * It deliberately covers a subset: paragraphs, % comments, $inline$ and
 * $$display$$ math, \[...\] blocks, \\ line breaks, a few text commands,
 * and \includegraphics{...} (rendered as a labelled figure placeholder).
 * Anything else passes through as plain text. Nothing here persists.
 */

export const MOCK_QUESTION_TEX = `% Mock sample - nothing is saved
A particle of mass $m$ moves along the $x$-axis under a potential
$V(x) = \\frac{1}{2} k x^2$. The total mechanical energy is $E$.

(a) Write the turning points in terms of $E$ and $k$.

(b) The period of oscillation is
$$
T = 2\\pi\\sqrt{\\frac{m}{k}}
$$
Show that $T$ is independent of $E$.

\\includegraphics{fig-q8-diagram.png}

Take $g = 10\\,\\mathrm{m/s^2}$ where needed.
`;

export const MOCK_SOLUTION_TEX = `% Mock sample - nothing is saved
\\textbf{Solution.} Turning points satisfy $E = V(x)$, i.e.
\\[
E = \\frac{1}{2} k x^2 \\quad\\Rightarrow\\quad x = \\pm\\sqrt{\\frac{2E}{k}}.
\\]
Hence the motion is bounded for $E > 0$, with amplitude
$A = \\sqrt{2E/k}$.

The period follows from
$$
T = \\sqrt{2m} \\int_{-A}^{A} \\frac{dx}{\\sqrt{E - kx^2/2}}
  = 2\\pi\\sqrt{\\frac{m}{k}},
$$
which has no $E$ dependence. \\textit{Therefore the oscillation is
isochronous.}
`;

function escapeHtml(s) {
	return s
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
}

function stripComments(tex) {
	return tex
		.split('\n')
		.map((line) => {
			if (line.trimStart().startsWith('%')) return '';
			let out = '';
			for (let i = 0; i < line.length; i++) {
				if (line[i] === '%' && line[i - 1] !== '\\') break;
				out += line[i];
			}
			return out;
		})
		.join('\n');
}

function inlineText(s) {
	// Assumes `s` is already HTML-escaped.
	return s
		.replace(/\\\\/g, '<br />')
		.replace(/\\textbf\{([^{}]*)\}/g, '<strong>$1</strong>')
		.replace(/\\textit\{([^{}]*)\}/g, '<em>$1</em>')
		.replace(/\\emph\{([^{}]*)\}/g, '<em>$1</em>')
		.replace(/\\mathrm\{([^{}]*)\}/g, '$1')
		.replace(/\\[,;!]/g, ' ')
		.replace(/\\quad|\\qquad/g, ' ')
		.replace(/\\(title|section|subsection|label|ref|cite)\{([^{}]*)\}/g, '$2');
}

/**
 * Convert mock TeX to reader-style HTML with KaTeX placeholders.
 * Math spans reuse the `.pl-math` / `.pl-math-block` contract filled in
 * by the workspace page (same KaTeX call as Segments.svelte).
 */
export function mockTexToHtml(tex) {
	const clean = stripComments(tex);
	const maths = [];
	const tokenize = (s, display) => {
		maths.push({ tex: s, display });
		return `\u0000MOCKMATH${maths.length - 1}\u0000`;
	};

	// Display math first (greedy-safe on single-line samples).
	let work = clean
		.replace(/\$\$([\s\S]+?)\$\$/g, (_, m) => tokenize(m.trim(), true))
		.replace(/\\\[([\s\S]+?)\\\]/g, (_, m) => tokenize(m.trim(), true));

	// Figures -> placeholders (kept out of math spans).
	const figs = [];
	work = work.replace(/\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}/g, (_, name) => {
		figs.push(name.trim());
		return `\u0000MOCKFIG${figs.length - 1}\u0000`;
	});

	// Inline math on the remainder.
	work = work.replace(/\$([^$\n]+?)\$/g, (_, m) => tokenize(m.trim(), false));

	const paras = work.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
	const html = paras
		.map((p) => {
			if (/^\u0000MOCKFIG\d+\u0000$/.test(p)) {
				const i = Number(p.match(/\d+/)[0]);
				const name = escapeHtml(figs[i]);
				return (
					`<figure class="mockfig" aria-label="Mock figure placeholder">` +
					`<span class="mockfig-box">Figure</span>` +
					`<figcaption class="pl-mono">${name} (mock)</figcaption></figure>`
				);
			}
			let h = escapeHtml(p).replace(/\n/g, '<br />');
			h = inlineText(h);
			h = h.replace(/\u0000MOCKMATH(\d+)\u0000/g, (_, i) => {
				const m = maths[Number(i)];
				const enc = encodeURIComponent(m.tex);
				const cls = m.display ? 'pl-math-block' : 'pl-math';
				return `<span class="${cls}" data-tex="${enc}" data-display="${m.display ? 1 : 0}"></span>`;
			});
			h = h.replace(/\u0000MOCKFIG(\d+)\u0000/g, (_, i) => {
				const name = escapeHtml(figs[Number(i)]);
				return (
					`<figure class="mockfig" aria-label="Mock figure placeholder">` +
					`<span class="mockfig-box">Figure</span>` +
					`<figcaption class="pl-mono">${name} (mock)</figcaption></figure>`
				);
			});
			return `<p>${h}</p>`;
		})
		.join('\n');
	return html || '<p class="pl-sub">Empty document.</p>';
}

/** Mock figure inventory for the workspace strip (no backend). */
export const MOCK_FIGURES = ['fig-q8-diagram.png', 'fig-q8-setup.png'];
