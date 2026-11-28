import { writable } from 'svelte/store';
import { api } from './api.js';

function persistent(key, fallback) {
	const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
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

/** 'light' | 'dark', applied to <html data-theme> by +layout.svelte. */
export const theme = persistent('ejee-theme', 'light');

/** Mobile navigation drawer state. */
export const sidebarOpen = writable(false);

/** Latest /api/status: missing settings, index, queue, counts, spend. */
export const appStatus = writable(null);

/** Short-lived notices ({id, text, tone}). */
export const toasts = writable([]);

let toastId = 0;
export function toast(text, tone = 'info', ms = 5000) {
	const id = ++toastId;
	toasts.update((list) => [...list, { id, text, tone }]);
	setTimeout(() => toasts.update((list) => list.filter((t) => t.id !== id)), ms);
}

export async function refreshStatus() {
	try {
		appStatus.set(await api.status());
	} catch {
		/* app offline: keep the last known status */
	}
}
