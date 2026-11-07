/**
 * Paper dressing (pure, display-only): remove the baked-in ORIGINAL
 * numbers from API segments so only generated Q-numbers show.
 *
 * Verified against the full Outputs tree (pattern census):
 * - Singles open as: bare stem (no number), `NN.`, `\textbf{NN.}`,
 *   `II-N.` — and mistune listifies a leading `NN.` stem into
 *   `<ol start="N">` (start omitted iff N==1) or plain `<ol>`.
 * - Passage headers: `Paragraph for Question Nos. A and|to B[:]?`,
 *   `Paragraph for Questions A and B`, bare `PARAGRAPH-I/II`, or absent.
 *   Sub-stems are `<ol start="NN">` for NN in dirname range a..b
 *   (contiguous in all 14 groups), or glued `\textbf{NN.}` (paper 4,
 *   never split by the backend).
 * - Solutions open `\textbf{Answer: QN) KEY}` + `Solution for QN`
 *   (math-encoded); QN may be `1`, `A-01`, `B-08`, `II-01`. Missing
 *   bodies read `No solution provided.` (plain or \textit).
 * - Options always render as `A)` paragraphs or table JSON — never as
 *   bare/started <ol> at stem position — so first-<ol> handling is safe.
 * - Table segments are kind:'table' (JSON cells); text regexes below
 *   only touch kind:'text' HTML and skip data-tex except via decode.
 *
 * Nothing here mutates stored data — new segment arrays are returned.
 */

const LEAD_TEXT_RE = /^(\s*(?:<p[^>]*>)?\s*)(?:<strong>\s*)?(?:[A-Za-z]+-)?\d+[a-z]?\.(?:\s*<\/strong>)?\s+/;
const FIRST_OL_RE = /^(\s*)<ol([^>]*)>/;
// Option paragraphs ("A) …") align under the stem text, not at the body
// margin — see the measured FITJEE/GTA/ADV rhythm. Tagged with pl-opt so
// sheet CSS can indent them exactly like list-item stems.
function markOptionParas(html) {
	return String(html ?? '').replace(/<p([^>]*)>([\s\S]*?)<\/p>/g, (m, attrs, inner) => {
		if (/class\s*=/.test(attrs)) return m;
		const text = inner.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
		if (!/^[A-D]\)/.test(text)) return m;
		return `<p${attrs} class="pl-opt">${inner}</p>`;
	});
}
// Passage headers arrive standalone (<p>Paragraph for Q Nos. 33 to 34:</p>,
// <p>PARAGRAPH-II</p>) OR glued to the body in one <p> (paper 8:
// <p>Paragraph for Question Nos. 33 to 34: Pitot tube is used...</p>).
// So strip the header PREFIX inside the first paragraph, keeping the body.
const PASSAGE_PREFIX_RE = /^(\s*<p[^>]*>\s*)(?:paragraph\s+for\s+questions?(?:\s+nos?\.?)?\s+[\d\s,.\-–andto]+:?\s*|paragraph\b[^<:\n]{0,60}:?\s*|PARAGRAPH\b[^<:\n]{0,40}:?\s*)/i;
const EMPTY_P_RE = /^<p[^>]*>\s*(?:<br\s*\/?>\s*)*<\/p>\s*/i;

/**
 * Dress question segments.
 * @param segments API segments (never mutated)
 * @param {{numbers:number[], para:{a:number,b:number,valid:boolean}|null}}
 */
export function dressQuestion(segments, { numbers = [], para = null } = {}) {
	const out = (segments ?? []).map((s) => (s.kind === 'text' ? { ...s } : s));
	const firstText = out.find((s) => s.kind === 'text');
	if (!firstText || numbers.length === 0) return out;

	if (para && para.valid && para.a != null) {
		// Passage: drop the header prefix (standalone or glued), keep body.
		firstText.html = firstText.html.replace(PASSAGE_PREFIX_RE, '$1');
		firstText.html = firstText.html.replace(EMPTY_P_RE, '');
		// ...and relabel sub-stems a..b to generated numbers, in order.
		// <ol start="NN"> stems:
		const html = out.map((s) => (s.kind === 'text' ? s.html : null));
		for (let k = 0; k < numbers.length; k++) {
			const orig = para.a + k;
			for (let i = 0; i < html.length; i++) {
				if (html[i] == null) continue;
				const re = new RegExp(`(<ol[^>]*\\bstart=")${orig}(")`);
				if (re.test(html[i])) {
					html[i] = html[i].replace(re, `$1${numbers[k]}$2`);
					break; // first occurrence in document order only
				}
			}
		}
		// Glued \textbf{NN.} stems (backend never splits these):
		for (let k = 0; k < numbers.length; k++) {
			const orig = para.a + k;
			const re = new RegExp(`(<strong>\\s*)${orig}(\\.\\s*<\\/strong>)`);
			for (let i = 0; i < html.length; i++) {
				if (html[i] == null) continue;
				if (re.test(html[i])) {
					html[i] = html[i].replace(re, `$1Q${numbers[k]}$2`);
					break;
				}
			}
		}
		out.forEach((s, i) => {
			if (s.kind === 'text') s.html = html[i];
		});
		for (const s of out) {
			if (s.kind === 'text' && typeof s.html === 'string') s.html = markOptionParas(s.html);
		}
		return out;
	}

	// Single: the stem wrapper carries the original number as its position.
	if (FIRST_OL_RE.test(firstText.html)) {
		firstText.html = firstText.html.replace(FIRST_OL_RE, (m, sp, attrs) =>
			/\bstart="/.test(attrs)
				? `${sp}<ol${attrs.replace(/\bstart="[^"]*"/, `start="${numbers[0]}"`)}>`
				: `${sp}<ol${attrs} start="${numbers[0]}">`
		);
	} else {
		firstText.html = firstText.html.replace(LEAD_TEXT_RE, '$1');
	}
	for (const s of out) {
		if (s.kind === 'text' && typeof s.html === 'string') s.html = markOptionParas(s.html);
	}
	return out;
}

// True when HTML carries visible content: real text, math (which lives in
// data-tex attributes with no inner text until KaTeX renders), images,
// figures or tables. Tag-stripped text alone misclassifies math-only
// solutions as empty — the exact bug that blanked Solutions Q7–Q8.
function segHasContent(html) {
	if (!html) return false;
	if (/data-tex|<(img|figure|table|svg|canvas)\b/i.test(html)) return true;
	return html.replace(/<[^>]*>/g, '').trim() !== '';
}

// A paragraph whose only content is a "Solution for X" label (math-form
// underline/bold data-tex, or plain text). These duplicate the sheet's own
// "Solution Qn" heading, so the first is dropped and later ones (which mark
// sub-solution boundaries in paragraph groups) become light dividers.
function isSolutionLabelPara(html) {
	const m = /^[\s\S]*?<p[^>]*>([\s\S]*?)<\/p>\s*$/.exec(html.trim());
	if (!m) return false;
	const inner = m[1];
	const text = inner.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
	if (/^Solution for\s+[A-Za-z0-9-]+\.?$/i.test(text)) return true;
	if (text) return false;
	for (const e of inner.matchAll(/data-tex="([^"]*)"/g)) {
		try {
			if (/Solution for/i.test(decodeURIComponent(e[1]))) return true;
		} catch { /* ignore bad encoding */ }
	}
	return false;
}

// A paragraph that is nothing but a filed cross-reference note ("(Q.14-15):").
// These duplicate the sheet's own "Solution Qn" heading — drop the para,
// or strip the marker when it leads a content paragraph. Position within
// the segment must not matter: markers ride mid-segment (paper 13 puts
// Answer/label paras first), so this runs per paragraph, never anchored
// to the segment start.
const QREF_BARE_RE = /^\(?\s*Q\.?\s*[\d][\d\s,.\-–]*\)?\s*:?\s*$/i;

function stripQRefPrefix(inner) {
	// Match the marker in TEXT space (tags skipped), then delete exactly
	// those text chars from the HTML. Tags are never touched, so markup
	// stays balanced whatever wraps the marker (<strong>, plain, ...).
	// Paras starting with a math span have no leading text: untouched.
	const text = inner.replace(/<[^>]*>/g, '');
	const mm = /^((?:\(\s*)?Q\.?\s*[\d][\d\s,.\-–]*\)?\s*:?\s+)/i.exec(text);
	if (!mm) return inner;
	let take = mm[0].length;
	let res = '';
	let i = 0;
	while (i < inner.length) {
		if (inner[i] === '<') {
			const j = inner.indexOf('>', i);
			res += j < 0 ? inner.slice(i) : inner.slice(i, j + 1);
			i = j < 0 ? inner.length : j + 1;
			continue;
		}
		if (take > 0) {
			take--;
			i++;
			continue;
		}
		res += inner[i];
		i++;
	}
	// Tidy emptied wrappers (never math spans: those hold content).
	return res.replace(/<(strong|em|b|i|u)(\s[^>]*)?>\s*<\/\1>/gi, '');
}

function isQRefPara(html) {
	const m = /^[\s\S]*?<p[^>]*>([\s\S]*?)<\/p>\s*$/.exec(html.trim());
	if (!m) return false;
	const text = m[1].replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
	return QREF_BARE_RE.test(text);
}

// A paragraph holding nothing but the filed answer line. Two shapes on
// the real corpus: "Answer: NN) KEY" (217 paras) and the plain-text repeat
// "Correct answer is (X)" (5 paras, paper 11 — duplicates the key table).
// The anchored "answer is" keeps prose like "Correct Step-by-Step
// Analysis:" (8/27) safely out of reach.
export function isAnswerPara(html) {
	const text = html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
	return /^Answer:\s*[^)]+\)\s*\S[^<>]*$/.test(text)
		|| /^Answer:\s*[^)]+\)\s*$/.test(text)
		|| /^Correct answer is\s*\([^)]*\)\.?\s*$/i.test(text);
}

/**
 * Extract filed keys from RAW solution segments, in block order:
 * "Answer: A-01) A, C" -> "A, C". One entry per Answer paragraph.
 */
export function extractAnswerKeys(segments) {
	const keys = [];
	for (const s of segments ?? []) {
		if (s?.kind !== 'text' || typeof s.html !== 'string') continue;
		for (const m of s.html.matchAll(/<p[^>]*>([\s\S]*?)<\/p>/g)) {
			const text = m[1].replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
			const k = text.match(/^Answer:\s*[^)]+\)\s*(\S[^<>]*?)\s*$/);
			if (k) keys.push(k[1].trim());
		}
	}
	return keys;
}

/**
 * Dress solution segments: drop filed Answer paragraphs (the key table
 * owns answers now) and relabel "Solution for A-17" (URL-encoded in
 * data-tex) to generated Q-numbers, preserving order of appearance.
 * Bodies reading "No solution provided." are left for the missing
 * placeholder (see AnswerSheetPreview).
 */
export function dressSolution(segments, { numbers = [] } = {}) {
	if (!numbers.length) return segments;
	const out = [];
	for (const s of segments ?? []) {
		if (s?.kind !== 'text' || typeof s.html !== 'string') { out.push(s); continue; }
		// Strip answer-only paragraphs entirely; Solution-for labels are
		// handled in the next pass (first dropped, later ones -> dividers).
		const stripped = s.html.replace(/<p[^>]*>[\s\S]*?<\/p>/g, (m) => (isAnswerPara(m) ? '' : m));
		out.push({ ...s, html: stripped });
	}
	// Dedup filed "Solution for X" labels against the sheet's own heading.
	let labelSeen = false;
	for (const s of out) {
		if (s.kind !== 'text' || typeof s.html !== 'string') continue;
		s.html = s.html.replace(/<p[^>]*>[\s\S]*?<\/p>/g, (m) => {
			if (isQRefPara(m)) return '';
			if (!isSolutionLabelPara(m)) {
				// Cross-ref marker leading a content para: strip it, keep
				// the rest. A para reduced to bare tags is dropped; one
				// reduced to a lone math span is real content — kept.
				const pm = /^<p([^>]*)>([\s\S]*?)<\/p>$/.exec(m);
				if (!pm) return m;
				const stripped = stripQRefPrefix(pm[2]);
				if (stripped === pm[2]) return m;
				if (stripped.replace(/<[^>]*>/g, '').trim() === '' && !/data-tex/.test(stripped)) return '';
				return `<p${pm[1]}>${stripped}</p>`;
			}
			if (!labelSeen) { labelSeen = true; return ''; }
			return '<hr class="sol-div">';
		});
	}
	// Drop segments left with no content (key-only solutions surface as
	// the explicit note in AnswerSheetPreview).
	for (let i = out.length - 1; i >= 0; i--) {
		const s = out[i];
		if (s?.kind === 'text' && typeof s.html === 'string' && !segHasContent(s.html)) out.splice(i, 1);
	}
	let si = 0;
	for (const s of out) {
		if (s.kind !== 'text' || typeof s.html !== 'string') continue;
		s.html = s.html.replace(/data-tex="([^"]*)"/g, (m, enc) => {
			let dec;
			try {
				dec = decodeURIComponent(enc);
			} catch {
				return m;
			}
			if (!/Solution for [A-Za-z0-9-]+/.test(dec)) return m;
			dec = dec.replace(/Solution for [A-Za-z0-9-]+/g, (mm) =>
				si < numbers.length ? `Solution for Q${numbers[si++]}` : mm);
			return `data-tex="${encodeURIComponent(dec)}"`;
		});
	}
	for (const s of out) {
		if (s.kind === 'text' && typeof s.html === 'string') s.html = markOptionParas(s.html);
	}
	return out;
}

/** True when filed solution text is the "No solution provided." marker. */
export function isMissingSolutionText(segments) {
	let text = '';
	for (const s of segments ?? []) {
		if (s?.kind === 'text' && typeof s.html === 'string')
			text += s.html.replace(/<[^>]*>/g, ' ');
	}
	return /no solution provided\.?/i.test(text.replace(/\s+/g, ' ').trim());
}
