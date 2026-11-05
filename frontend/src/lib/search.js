/**
 * Search page state: filters + loaded results + cursor + scroll, persisted
 * in sessionStorage so opening a question and coming back (Back button,
 * browser Back/Forward, or reload) restores everything exactly.
 * Tab-scoped on purpose: a fresh tab starts with clean filters.
 */
import { browser } from '$app/environment';

export const SEARCH_KEY = 'pl-search-v2';
export const PAGE_SIZE = 15;

export const FILTER_KEYS = ['qtype', 'difficulty', 'exam', 'institute', 'year', 'topic'];

export function defaultFilters() {
	return { qtype: [], difficulty: [], exam: [], institute: [], year: [], topic: [] };
}

export function activeFilterCount(filters) {
	return FILTER_KEYS.reduce((n, k) => n + (filters?.[k]?.length ?? 0), 0);
}

export function loadSearchState() {
	if (!browser) return null;
	try {
		const raw = sessionStorage.getItem(SEARCH_KEY);
		if (!raw) return null;
		const s = JSON.parse(raw);
		if (!s || typeof s !== 'object') return null;
		const filters = { ...defaultFilters(), ...(s.filters ?? {}) };
		for (const k of FILTER_KEYS) {
			if (!Array.isArray(filters[k])) filters[k] = [];
			filters[k] = filters[k].map(String);
		}
		return {
			filters,
			items: Array.isArray(s.items) ? s.items : [],
			total: typeof s.total === 'number' ? s.total : 0,
			nextCursor: s.nextCursor ?? null,
			hasMore: !!s.hasMore,
			scrollY: typeof s.scrollY === 'number' ? s.scrollY : 0
		};
	} catch {
		return null;
	}
}

export function saveSearchState(state) {
	if (!browser) return;
	try {
		sessionStorage.setItem(
			SEARCH_KEY,
			JSON.stringify({
				filters: state.filters,
				items: state.items,
				total: state.total,
				nextCursor: state.nextCursor,
				hasMore: state.hasMore,
				scrollY: state.scrollY ?? 0
			})
		);
	} catch {
		/* private mode: stay in memory */
	}
}

export function clearSearchResults(state) {
	state.items = [];
	state.total = 0;
	state.nextCursor = null;
	state.hasMore = false;
}
