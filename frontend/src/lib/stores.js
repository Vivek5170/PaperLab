import { writable } from 'svelte/store';

function persistent(key, fallback) {
	const stored =
		typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
	const store = writable(stored ?? fallback);
	store.subscribe((value) => {
		try {
			localStorage.setItem(key, value);
		} catch {
			/* private mode: stay in memory */
		}
	});
	return store;
}

/** 'light' | 'dark' — applied to <html data-theme> by +layout.svelte. */
export const theme = persistent('pl-theme', 'light');

/**
 * 'student' | 'archivist'. The server session is the source of truth
 * (+layout syncs it from /api/auth/me on load); this only hides edit UI.
 */
export const role = persistent('pl-role', 'student');

/** Opens the archivist login dialog (rendered once in +layout). */
export const loginOpen = writable(false);

/** Global filter text shared by the sidebar search and list pages. */
export const searchQuery = writable('');

/** Mobile navigation drawer state. */
export const sidebarOpen = writable(false);

/** Tagging Inbox items, shared so layout badge and inbox page fetch once. */
export const inboxItems = writable(null);
/**
 * The inbox endpoint returns `{total, items}` but both writers must store
 * a plain array — the layout badge reads `.length` and the inbox page
 * reads `[index]`. Normalizing in one place means a slow fetch can never
 * clobber a good array with a raw response object (last-writer-wins races
 * stay harmless because both writers store the same shape).
 */
export const inboxList = (res) => (Array.isArray(res) ? res : (res?.items ?? null));
