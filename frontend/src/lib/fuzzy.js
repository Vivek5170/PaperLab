/**
 * Per-word fuzzy matching for paper names that don't follow a format.
 * Every query word must match somewhere (AND semantics); results rank by
 * mean word score. Typos handled two ways: substring/prefix matches win,
 * otherwise closest-token Levenshtein similarity above threshold counts.
 */

export function levenshtein(a, b) {
	if (a === b) return 0;
	if (!a.length) return b.length;
	if (!b.length) return a.length;
	let prev = new Array(b.length + 1);
	for (let j = 0; j <= b.length; j++) prev[j] = j;
	for (let i = 1; i <= a.length; i++) {
		let cur = new Array(b.length + 1);
		cur[0] = i;
		for (let j = 1; j <= b.length; j++) {
			cur[j] = Math.min(
				prev[j] + 1,
				cur[j - 1] + 1,
				prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)
			);
		}
		prev = cur;
	}
	return prev[b.length];
}

function wordScore(word, haystack) {
	if (haystack.includes(word)) return 1;
	let best = 0;
	for (const token of haystack.split(/[^a-z0-9]+/)) {
		if (!token || Math.abs(token.length - word.length) > 3) continue;
		if (token.startsWith(word) || word.startsWith(token)) {
			best = Math.max(best, 0.9);
			continue;
		}
		const sim = 1 - levenshtein(word, token) / Math.max(word.length, token.length);
		if (sim > best) best = sim;
	}
	return best >= 0.55 ? best : 0;
}

export function fuzzyFilter(items, query, haystackOf) {
	const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
	if (!words.length) return items;
	const scored = [];
	for (const item of items) {
		const hay = haystackOf(item).toLowerCase();
		let total = 0;
		let ok = true;
		for (const w of words) {
			const s = wordScore(w, hay);
			if (!s) {
				ok = false;
				break;
			}
			total += s;
		}
		if (ok) scored.push({ item, score: total / words.length });
	}
	scored.sort((a, b) => b.score - a.score);
	return scored.map((r) => r.item);
}
