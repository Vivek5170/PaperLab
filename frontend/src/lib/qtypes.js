/**
 * Display labels for question-type codes. The backend (and DB) keep the
 * original codes (scq/msq/...) so the pipeline and API are untouched;
 * only what users see is shortened. `value` sent back to the API must
 * always stay the raw code.
 */
const SHORT = {
	scq: 'sca',
	msq: 'mca',
	'par-scq': 'par-sca',
	'par-msq': 'par-mca'
};

/** Short display label for one qtype code; unknown codes pass through. */
export const qtypeLabel = (code) => SHORT[code] ?? code ?? 'unknown';

/** Rewrite codes inside preformatted strings (e.g. "scq 4 - msq 3"). */
export const qtypeLabelAll = (text) =>
	String(text ?? '').replace(/\b(msq|scq)\b/g, (m) => SHORT[m]);

/**
 * Normalized answer type for section validation (builder, Phase 2).
 * Raw qtype stays the source of truth for rendering; `par-` prefix is
 * only stripped for grouping: par-scq -> scq, par-msq -> mca-group msq,
 * par-mix -> mix (stays distinct, never merges). Non-par codes pass
 * through; nullish -> 'unknown'.
 */
export const normalizeAnswerType = (code) => {
	if (code == null) return 'unknown';
	const c = String(code).trim().toLowerCase() || 'unknown';
	return c.startsWith('par-') ? c.slice(4) || 'mix' : c;
};
