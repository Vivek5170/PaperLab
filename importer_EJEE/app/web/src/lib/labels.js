// Display labels shared by search, cart and process pages.

export const STATUS_LABEL = {
	not_started: 'Not started',
	in_cart: 'In cart',
	queued: 'Queued',
	running: 'Processing',
	needs_review: 'Needs review',
	failed: 'Failed',
	published: 'Published',
	done: 'Published'
};

export const ANSWER_LABEL = {
	solution: 'Worked solution',
	key: 'Answer key only',
	none: 'Question only'
};

export const STAGE_LABEL = {
	prepare: 'Prepare',
	extract: 'Transcribe',
	figures: 'Figures',
	pack: 'Pack',
	classify: 'Tag topics',
	verify: 'Verify',
	export: 'Bundle',
	upload: 'Publish'
};

export const CATEGORY_SHORT = {
	Textbook: 'Textbook',
	'Institute study material': 'Institute material',
	'Institute test papers': 'Test paper',
	'Past-year questions': 'PYQ',
	'Exam papers': 'Exam paper',
	Olympiad: 'Olympiad'
};

export const statusLabel = (s) => STATUS_LABEL[s] ?? s ?? '';
export const answerLabel = (a) => ANSWER_LABEL[a] ?? a;

// Measured pilot range (EJEE_SOURCES.md §4a): key-only cards ~$0.0011/q up to
// dense printed modules ~$0.0052/q. Photo olympiads can reach ~$0.015/q.
export const RATE = { low: 0.0011, high: 0.0052, inr: 92.89, gst: 0.18 };

export function estimate(questions) {
	const lo = questions * RATE.low;
	const hi = questions * RATE.high;
	return {
		usd: `$${lo.toFixed(2)}–$${hi.toFixed(2)}`,
		inrGst: `₹${Math.round(lo * RATE.inr * (1 + RATE.gst))}–₹${Math.round(hi * RATE.inr * (1 + RATE.gst))}`
	};
}

export function money(m) {
	if (!m) return '';
	return `$${Number(m.usd).toFixed(4)} · ₹${Number(m.inr).toFixed(2)} · ₹${Number(m.inr_gst).toFixed(2)} incl. GST`;
}
