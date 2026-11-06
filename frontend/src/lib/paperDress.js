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
const PASSAGE_HEAD_RE = /^<p[^>]*>\s*(?:paragraph\s+for\s+questions?(?:\s+nos?\.?)?\s+[\d\s,\-–andto]+:?|paragraph\b[^<]*|PARAGRAPH\b[^<]*)\s*<\/p>\s*/i;

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
		// Passage: drop the original-number header paragraph...
		firstText.html = firstText.html.replace(PASSAGE_HEAD_RE, '');
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
	return out;
}

// A paragraph holding nothing but the filed answer line.
function isAnswerPara(html) {
	const text = html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
	return /^Answer:\s*[^)]+\)\s*\S[^<>]*$/.test(text) || /^Answer:\s*[^)]+\)\s*$/.test(text);
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
 * placeholder (see SolutionBlock).
 */
export function dressSolution(segments, { numbers = [] } = {}) {
	if (!numbers.length) return segments;
	const out = [];
	for (const s of segments ?? []) {
		if (s?.kind !== 'text' || typeof s.html !== 'string') { out.push(s); continue; }
		// Strip answer-only paragraphs entirely.
		const stripped = s.html.replace(/<p[^>]*>[\s\S]*?<\/p>/g, (m) => (isAnswerPara(m) ? '' : m));
		if (stripped.replace(/<[^>]*>/g, '').trim() === '' && s.html !== stripped) continue;
		out.push({ ...s, html: stripped });
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
