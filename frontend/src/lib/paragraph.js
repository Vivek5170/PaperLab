/**
 * Paragraph-group identity helpers (pure, no Svelte/store deps).
 *
 * Agent contract (tools_extractor.submit_question docstring + prompts):
 * - `question_number` is always a STRING: "1", "15a", "15-17_paragraph".
 * - A passage group is ONE question row ("31-32_paragraph"), never
 *   sub-questions; namespaced repeats use "<SEC>-<NN>" ("B-31-32_paragraph").
 * - directory_manager preserves the id verbatim; DB enforces
 *   UNIQUE(paper_id, question_number).
 *
 * Display splitting (render.py:_split_group_stems) only fires for dirs
 * matching /(\d{1,3})-(\d{1,3})_paragraph$/ with a<b<=a+12. The parser
 * below mirrors that bound so numbering never invents sub-slots the
 * renderer can't display.
 */

const RANGE_SUFFIX_RE = /(\d{1,3})-(\d{1,3})_paragraph$/;
const PARAGRAPH_HINT_RE = /paragraph/i;
const MAX_SPAN = 12;

/**
 * Parse a question_number for a paragraph range.
 * Suffix-based: "B-31-32_paragraph" matches via its "31-32_paragraph" tail.
 *
 * Returns {isParagraph, a, b, count, valid, warning}. Never throws.
 * - Plain ids ("8", "15a", "A-01") -> {isParagraph:false, count:1}.
 * - Valid range -> {isParagraph:true, count:b-a+1, valid:true}.
 * - "paragraph" in the id but no valid range, or reversed/oversized
 *   ranges, or a par-* qtype without a range -> valid:false with a
 *   human-readable `warning`; count falls back to 1 so callers never
 *   crash — the UI must surface the warning badge instead of silently
 *   treating it as a normal question.
 */
export function parseParagraphRange(number, qtype = '') {
	const raw = String(number ?? '');
	const m = raw.match(RANGE_SUFFIX_RE);
	if (m) {
		const a = parseInt(m[1], 10);
		const b = parseInt(m[2], 10);
		if (Number.isNaN(a) || Number.isNaN(b)) {
			return {
				isParagraph: true, a: null, b: null, count: 1, valid: false,
				warning: `Unrecognized paragraph id "${raw}": bad range numbers.`
			};
		}
		if (a >= b) {
			return {
				isParagraph: true, a, b, count: 1, valid: false,
				warning: `Paragraph range reversed in "${raw}" (expected start < end). Treated as one question.`
			};
		}
		if (b - a + 1 > MAX_SPAN) {
			return {
				isParagraph: true, a, b, count: 1, valid: false,
				warning: `Paragraph span too large in "${raw}" (max ${MAX_SPAN} sub-questions). Treated as one question.`
			};
		}
		return { isParagraph: true, a, b, count: b - a + 1, valid: true, warning: null };
	}
	if (PARAGRAPH_HINT_RE.test(raw)) {
		return {
			isParagraph: true, a: null, b: null, count: 1, valid: false,
			warning: `Unrecognized paragraph id "${raw}": expected "<start>-<end>_paragraph". Treated as one question.`
		};
	}
	if (typeof qtype === 'string' && qtype.startsWith('par-')) {
		return {
			isParagraph: false, a: null, b: null, count: 1, valid: false,
			warning: `Question typed "${qtype}" but id "${raw}" has no paragraph range. Treated as one question.`
		};
	}
	return { isParagraph: false, a: null, b: null, count: 1, valid: true, warning: null };
}

/** True when the id carries a paragraph range (valid or not). */
export const isParagraphId = (number, qtype = '') =>
	parseParagraphRange(number, qtype).isParagraph;
