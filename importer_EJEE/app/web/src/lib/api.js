// Thin client for the EJEE Importer's own API (never PaperLab's).
// Every request carries the app header; the server refuses writes without it.

export class ApiError extends Error {
	constructor(message, status, detail) {
		super(message);
		this.status = status;
		this.detail = detail;
	}
}

async function req(method, path, body) {
	const headers = { 'x-ejee-app': '1' };
	if (body !== undefined) headers['content-type'] = 'application/json';
	let res;
	try {
		res = await fetch('/api' + path, {
			method,
			headers,
			body: body !== undefined ? JSON.stringify(body) : undefined
		});
	} catch {
		throw new ApiError('The EJEE Importer app is not responding. Is it still running?', 0, null);
	}
	let data = null;
	try {
		data = await res.json();
	} catch {
		/* empty body */
	}
	if (!res.ok) {
		const d = data?.detail;
		const msg = typeof d === 'string' ? d : (d?.message ?? `Request failed (${res.status}).`);
		throw new ApiError(msg, res.status, d);
	}
	return data;
}

const enc = encodeURIComponent;

export const api = {
	status: () => req('GET', '/status'),
	search: (filters, cursor = 0, limit = 24) => req('POST', '/search', { filters, cursor, limit }),
	facets: (filters) => req('POST', '/facets', { filters }),
	topics: () => req('GET', '/topics'),
	item: (source, key) => req('GET', `/item?source=${enc(source)}&key=${enc(key)}`),
	part: (slug, part) => req('GET', `/part/${enc(slug)}/${part}`),
	books: (q = '', category = []) => req('POST', '/books', { q, category }),
	convertBook: (slug, parts = 'all') => req('POST', '/books/cart', { slug, parts }),
	cart: () => req('GET', '/cart'),
	addPart: (slug, part) => req('POST', '/cart', { slug, part }),
	removePart: (slug, part) => req('DELETE', `/cart/${enc(slug)}/${part}`),
	clearCart: () => req('DELETE', '/cart'),
	settings: () => req('GET', '/settings'),
	saveSettings: (values) => req('PUT', '/settings', values),
	test: (what) => req('POST', '/settings/test', { what }),
	rebuildIndex: () => req('POST', '/index/rebuild'),
	jobs: () => req('GET', '/jobs'),
	start: () => req('POST', '/process/start'),
	pause: () => req('POST', '/process/pause'),
	resume: () => req('POST', '/process/resume'),
	retry: (id) => req('POST', `/jobs/${id}/retry`),
	removeJob: (id) => req('DELETE', `/jobs/${id}`),
	log: (id) => req('GET', `/jobs/${id}/log`)
};

/** Read-only preview of an EJEE source image (body crop). */
export const img = (rid, w = 480) => `/api/image/${rid}?w=${w}`;
export const fullImg = (rid) => `/api/image/${rid}?w=1600&full=true`;

export const itemHref = (item) => `/item?source=${enc(item.source)}&key=${enc(item.key)}`;
