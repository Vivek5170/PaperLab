/**
 * Pure cart-model helpers (no localStorage, no Svelte). carts.js wraps
 * these with persistence. Kept pure so node --test can cover them.
 *
 * Identity: {paperId:number, number:string}. Everything else is a
 * re-fetchable snapshot (plain text + URL strings only — never segments,
 * HTML, or image bytes).
 */

export const CART_SCHEMA_VERSION = 1;
export const MAX_CARTS = 50;
export const MAX_ITEMS_PER_CART = 2000;

const isValidId = (v) => typeof v === 'number' && Number.isFinite(v);
const cleanStr = (v, max = 500) =>
	typeof v === 'string' ? v.slice(0, max) : v == null ? v : String(v).slice(0, max);

export function newId() {
	try {
		if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
	} catch { /* fall through */ }
	return `c-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;
}

export function createCart(name = 'Untitled cart') {
	const now = new Date().toISOString();
	return {
		id: newId(),
		name: String(name ?? 'Untitled cart').slice(0, 80) || 'Untitled cart',
		createdAt: now,
		updatedAt: now,
		items: []
	};
}

/** Minimal snapshot for one question. Extra fields are dropped. */
export function toCartItem(src) {
	if (!src || typeof src !== 'object') return null;
	const paperId = typeof src.paperId === 'string' ? parseInt(src.paperId, 10) : src.paperId;
	const number = src.number != null ? String(src.number) : '';
	if (!isValidId(paperId) || !number) return null;
	return {
		paperId,
		number,
		qtype: cleanStr(src.qtype ?? 'unknown', 20) || 'unknown',
		difficulty: src.difficulty ?? null,
		preview: cleanStr(src.preview ?? '', 300),
		thumb: typeof src.thumb === 'string' ? src.thumb.slice(0, 500) : null,
		exam: cleanStr(src.exam ?? '', 80) || '',
		year: src.year ?? null,
		institute: cleanStr(src.institute ?? '', 120) || '',
		addedAt: src.addedAt ?? new Date().toISOString()
	};
}

export const itemKey = (paperId, number) => `${paperId}::${String(number)}`;

export function findItemIndex(cart, paperId, number) {
	const k = itemKey(paperId, number);
	return cart.items.findIndex((it) => itemKey(it.paperId, it.number) === k);
}

/** Add; returns {cart, added:boolean, reason}. Never mutates input. */
export function addItem(cart, src) {
	const item = toCartItem(src);
	if (!item) return { cart, added: false, reason: 'invalid' };
	if (findItemIndex(cart, item.paperId, item.number) !== -1)
		return { cart, added: false, reason: 'duplicate' };
	if (cart.items.length >= MAX_ITEMS_PER_CART)
		return { cart, added: false, reason: 'full' };
	const now = new Date().toISOString();
	return {
		cart: { ...cart, updatedAt: now, items: [...cart.items, item] },
		added: true, reason: 'ok'
	};
}

/** Remove by identity; returns {cart, removed:boolean}. */
export function removeItem(cart, paperId, number) {
	const i = findItemIndex(cart, paperId, number);
	if (i === -1) return { cart, removed: false };
	const items = cart.items.slice();
	items.splice(i, 1);
	return { cart: { ...cart, updatedAt: new Date().toISOString(), items }, removed: true };
}

/**
 * Reorder: move item from index `from` to index `to` (clamped).
 * Paragraph groups move as one row automatically — a group is a single
 * item, so there is no sub-move to preserve.
 */
export function moveItem(cart, from, to) {
	const n = cart.items.length;
	if (n < 2) return { cart, moved: false };
	const f = Math.max(0, Math.min(n - 1, from | 0));
	const t = Math.max(0, Math.min(n - 1, to | 0));
	if (f === t) return { cart, moved: false };
	const items = cart.items.slice();
	const [row] = items.splice(f, 1);
	items.splice(t, 0, row);
	return { cart: { ...cart, updatedAt: new Date().toISOString(), items }, moved: true };
}

/** Validate a parsed store blob; returns {ok, store} with repairs applied. */
export function validateStore(raw) {
	const fresh = () => {
		const c = createCart('My first cart');
		return { version: CART_SCHEMA_VERSION, activeId: c.id, carts: [c] };
	};
	if (!raw || typeof raw !== 'object') return { ok: false, store: fresh() };
	const carts = Array.isArray(raw.carts) ? raw.carts : [];
	const clean = [];
	for (const c of carts.slice(0, MAX_CARTS)) {
		if (!c || typeof c !== 'object') continue;
		const items = Array.isArray(c.items) ? c.items : [];
		const seen = new Set();
		const good = [];
		for (const it of items.slice(0, MAX_ITEMS_PER_CART)) {
			const norm = toCartItem(it);
			if (!norm) continue;
			const k = itemKey(norm.paperId, norm.number);
			if (seen.has(k)) continue; // drop dupes from corrupt/manual edits
			seen.add(k);
			good.push(norm);
		}
		clean.push({
			id: typeof c.id === 'string' && c.id ? c.id : newId(),
			name: String(c.name ?? 'Untitled cart').slice(0, 80) || 'Untitled cart',
			createdAt: c.createdAt ?? new Date().toISOString(),
			updatedAt: c.updatedAt ?? new Date().toISOString(),
			items: good
		});
	}
	if (clean.length === 0) {
		const c = createCart('My first cart');
		return { ok: false, store: { version: CART_SCHEMA_VERSION, activeId: c.id, carts: [c] } };
	}
	let activeId = typeof raw.activeId === 'string' ? raw.activeId : null;
	if (!clean.some((c) => c.id === activeId)) activeId = clean[0].id;
	return { ok: true, store: { version: CART_SCHEMA_VERSION, activeId, carts: clean } };
}
