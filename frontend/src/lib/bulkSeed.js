/**
 * Bulk-seed planning for sheet loaders (pure, no deps, node-testable).
 *
 * The backend's bulk endpoint GET /papers/{id}/questions returns the exact
 * same detail objects as the single endpoint (same _question_detail
 * constructor), so seeding the session cache from one bulk fetch preserves
 * API responses and cache behaviour exactly: same bytes in, same objects
 * out, failures never cached.
 *
 * A bulk fetch costs one handler plus a full-paper parse (~48ms) versus
 * ~6ms per single, so only groups of BULK_SEED_MIN or more go bulk; the
 * rest keep the cheap single path. Bulk failure falls through to
 * individual fetches — never worse than today.
 */

export const BULK_SEED_MIN = 3;

/**
 * Split missing entries into bulk groups.
 * The caller still fetches every missing entry individually afterwards;
 * seeded numbers resolve from cache (no network), the rest fetch as
 * before. Bulk failure changes nothing — singles cover everything.
 * @param missing [{paperId, number, ...}]
 * @returns {bulk: [{paperId, numbers[]}]}
 */
export function bulkSeedPlan(missing) {
	const groups = new Map();
	for (const e of missing ?? []) {
		if (e?.paperId == null) continue;
		if (!groups.has(e.paperId)) groups.set(e.paperId, []);
		groups.get(e.paperId).push(e.number);
	}
	const bulk = [];
	for (const [paperId, numbers] of groups) {
		if (numbers.length >= BULK_SEED_MIN) bulk.push({ paperId, numbers });
	}
	return { bulk };
}

/**
 * Seed session-cache entries from a bulk response.
 * @returns numbers actually seeded (absent numbers fall back to singles)
 */
export function applyBulkSeed(seedFn, paperId, items, wanted) {
	const byNumber = new Map(
		(items ?? []).map((it) => [String(it?.number), it])
	);
	const seeded = [];
	for (const n of wanted ?? []) {
		const it = byNumber.get(String(n));
		if (it !== undefined) {
			seedFn(paperId, n, it);
			seeded.push(n);
		}
	}
	return seeded;
}
