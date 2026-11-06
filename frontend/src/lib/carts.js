/**
 * Named question carts, client-side only (localStorage `pl-carts-v1`).
 * Identity is {paperId, number}; snapshots are plain text + URL strings
 * (never segments/HTML/image bytes). All writes are guarded so private
 * mode, quota errors, or corrupt JSON can never break the page.
 */
import { browser } from '$app/environment';
import { writable, derived } from 'svelte/store';
import {
	CART_SCHEMA_VERSION,
	createCart,
	addItem as _add,
	removeItem as _remove,
	moveItem as _move,
	validateStore,
	toCartItem
} from './cartModel.js';

export const CART_KEY = 'pl-carts-v1';

function loadInitial() {
	const fresh = createCart('My first cart');
	const blank = { version: CART_SCHEMA_VERSION, activeId: fresh.id, carts: [fresh] };
	if (!browser) return { store: blank, corrupt: false };
	try {
		const raw = localStorage.getItem(CART_KEY);
		if (!raw) return { store: blank, corrupt: false };
		const { ok, store } = validateStore(JSON.parse(raw));
		return { store, corrupt: !ok };
	} catch {
		return { store: blank, corrupt: true };
	}
}

const initial = loadInitial();

/** True when startup found corrupt JSON (page shows a one-time notice). */
export const cartCorrupt = writable(initial.corrupt);

function persist(store) {
	if (!browser) return;
	try {
		localStorage.setItem(CART_KEY, JSON.stringify(store));
	} catch {
		/* quota/private mode: keep in-memory copy, stay functional */
	}
}

persist(initial.store);
if (browser && initial.corrupt) {
	try {
		localStorage.setItem(
			`${CART_KEY}-corrupt-${Date.now()}`,
			localStorage.getItem(CART_KEY) ?? ''
		);
	} catch { /* best-effort backup */ }
}

export const cartStore = writable(initial.store);

if (browser) {
	cartStore.subscribe((s) => persist(s));
	try {
		window.addEventListener('storage', (e) => {
			if (e.key !== CART_KEY || !e.newValue) return;
			try {
				const { ok, store } = validateStore(JSON.parse(e.newValue));
				if (ok) cartStore.set(store);
			} catch { /* ignore cross-tab garbage */ }
		});
	} catch { /* no window */ }
}

const patchActive = (fn) => {
	cartStore.update((s) => {
		const cart = s.carts.find((c) => c.id === s.activeId) ?? s.carts[0];
		if (!cart) return s;
		const out = fn(cart);
		if (!out) return s;
		return {
			...s,
			carts: s.carts.map((c) => (c.id === cart.id ? out : c))
		};
	});
};

export const activeCart = derived(cartStore, ($s) => {
	return $s.carts.find((c) => c.id === $s.activeId) ?? $s.carts[0] ?? null;
});

export const cartCount = derived(activeCart, ($c) => $c?.items.length ?? 0);

export const carts = {
	create(name) {
		let id = null;
		cartStore.update((s) => {
			const c = createCart(name?.trim() || `Cart ${s.carts.length + 1}`);
			id = c.id;
			return { ...s, activeId: c.id, carts: [...s.carts, c] };
		});
		return id;
	},
	rename(id, name) {
		const clean = String(name ?? '').trim().slice(0, 80);
		if (!clean) return false;
		cartStore.update((s) => ({
			...s,
			carts: s.carts.map((c) =>
				c.id === id ? { ...c, name: clean, updatedAt: new Date().toISOString() } : c)
		}));
		return true;
	},
	duplicate(id) {
		let nid = null;
		cartStore.update((s) => {
			const src = s.carts.find((c) => c.id === id);
			if (!src) return s;
			const copy = {
				...createCart(`${src.name} (copy)`),
				items: src.items.map((it) => ({ ...toCartItem(it) }))
			};
			nid = copy.id;
			return { ...s, activeId: copy.id, carts: [...s.carts, copy] };
		});
		return nid;
	},
	delete(id) {
		cartStore.update((s) => {
			const carts = s.carts.filter((c) => c.id !== id);
			if (carts.length === 0) {
				const c = createCart('My first cart');
				return { ...s, activeId: c.id, carts: [c] };
			}
			return {
				...s,
				activeId: s.activeId === id ? carts[0].id : s.activeId,
				carts
			};
		});
	},
	switch(id) {
		cartStore.update((s) =>
			s.carts.some((c) => c.id === id) ? { ...s, activeId: id } : s);
	},
	clear() {
		patchActive((cart) => ({ ...cart, items: [], updatedAt: new Date().toISOString() }));
	},
	/** Returns 'ok' | 'duplicate' | 'invalid' | 'full'. */
	add(src) {
		let status = 'invalid';
		patchActive((cart) => {
			const r = _add(cart, src);
			status = r.added ? 'ok' : r.reason;
			return r.cart;
		});
		return status;
	},
	remove(paperId, number) {
		let done = false;
		patchActive((cart) => {
			const r = _remove(cart, paperId, number);
			done = r.removed;
			return r.cart;
		});
		return done;
	},
	has(paperId, number) {
		let found = false;
		const unsub = activeCart.subscribe((cart) => {
			found = !!cart?.items.some(
				(it) => it.paperId === paperId && String(it.number) === String(number));
		});
		unsub();
		return found;
	},
	move(from, to) {
		let moved = false;
		patchActive((cart) => {
			const r = _move(cart, from, to);
			moved = r.moved;
			return r.cart;
		});
		return moved;
	}
};
