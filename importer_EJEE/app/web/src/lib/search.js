// Search state: filters + loaded page, kept for the browser session so
// "back" from a question returns to the same list and scroll position.

export const PAGE_SIZE = 24;
export const FILTER_KEYS = ['category', 'source', 'qtype', 'difficulty', 'exam', 'year', 'answer', 'status', 'topic'];

export function defaultFilters() {
	return {
		q: '',
		category: [],
		source: [],
		qtype: [],
		difficulty: [],
		exam: [],
		year: [],
		answer: [],
		status: [],
		topic: []
	};
}

export function activeFilterCount(f) {
	return FILTER_KEYS.reduce((n, k) => n + (f[k]?.length ?? 0), 0) + (f.q?.trim() ? 1 : 0);
}

// v2: questions only, no "convertible" toggle (old saved state is ignored).
const KEY = 'ejee-search-state-v2';

export function loadSearchState() {
	try {
		const raw = sessionStorage.getItem(KEY);
		if (!raw) return null;
		const state = JSON.parse(raw);
		state.filters = { ...defaultFilters(), ...(state.filters ?? {}) };
		return state;
	} catch {
		return null;
	}
}

export function saveSearchState(state) {
	try {
		sessionStorage.setItem(KEY, JSON.stringify(state));
	} catch {
		/* quota: skip */
	}
}

export function clearSearchState() {
	try {
		sessionStorage.removeItem(KEY);
	} catch {
		/* ignore */
	}
}
