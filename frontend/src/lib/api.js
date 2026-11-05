/**
 * REST client for the PaperLab backend.
 *
 * Base URL defaults to same-origin /api (vite proxies it to
 * http://127.0.0.1:8000 in dev). Override with VITE_API_BASE.
 * Every function below maps 1:1 to BACKEND_CONTRACT.md.
 */

const BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '');

async function request(path, options = {}) {
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), 30000);
	let res;
	try {
		res = await fetch(`${BASE}${path}`, {
			headers: { 'Content-Type': 'application/json' },
			...options,
			signal: controller.signal
		});
	} catch (e) {
		clearTimeout(timer);
		if (e.name === 'AbortError') throw new Error('Request timed out - is the backend running?');
		throw new Error('Cannot reach the backend - is it running?');
	}
	clearTimeout(timer);
	if (!res.ok) {
		let detail = res.statusText;
		try {
			detail = (await res.json()).detail || detail;
		} catch {
			/* keep status text */
		}
		throw new Error(`${res.status}: ${detail}`);
	}
	if (res.status === 204) return null;
	return res.json();
}

export const api = {
	health: () => request('/health'),

	listPapers: (params = {}) => {
		const q = new URLSearchParams(
			Object.entries(params).filter(([, v]) => v !== '' && v != null)
		).toString();
		return request(`/papers${q ? `?${q}` : ''}`);
	},
	getPaper: (id) => request(`/papers/${id}`),
	getLibrarySummary: () => request('/papers/summary'),
	getQuestions: (id) => request(`/papers/${id}/questions`),
	getQuestion: (paperId, qn) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}`),

	getInbox: () => request('/inbox'),
	classifyQuestion: (paperId, qn, body) =>
		request(`/papers/${paperId}/questions/${encodeURIComponent(qn)}`, {
			method: 'PATCH',
			body: JSON.stringify(body)
		}),

	getTopics: () => request('/topics'),
	createTopic: (body) => request('/topics', { method: 'POST', body: JSON.stringify(body) }),
	updateTopic: (code, body) =>
		request(`/topics/${encodeURIComponent(code)}`, {
			method: 'PATCH',
			body: JSON.stringify(body)
		}),
	deleteTopic: (code) =>
		request(`/topics/${encodeURIComponent(code)}`, { method: 'DELETE' }),
	moveTopic: (code, newParent) =>
		request(`/topics/${encodeURIComponent(code)}/move`, {
			method: 'POST',
			body: JSON.stringify({ newParent })
		}),
	getTopicUsage: () => request('/topics/usage'),

	getStats: () => request('/stats'),

	listUploads: () => request('/uploads'),
	uploadFiles: (formData) =>
		request('/uploads', { method: 'POST', body: formData, headers: {} }),
	deleteUploads: (names) =>
		request('/uploads', { method: 'DELETE', body: JSON.stringify({ names }) }),
	suggestPairs: () => request('/uploads/pairs/suggest'),
	registerPairs: (pairs) =>
		request('/papers/register', { method: 'POST', body: JSON.stringify({ pairs }) }),

	getJobs: () => request('/jobs'),
	runPapers: (ids, mode = 'sequential', force = false) =>
		request('/jobs', { method: 'POST', body: JSON.stringify({ ids, mode, force }) }),
	deletePaper: (id) => request(`/papers/${id}`, { method: 'DELETE' }),

	login: (password) =>
		request('/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
	logout: () => request('/auth/logout', { method: 'POST' }),
	me: () => request('/auth/me'),
	getMeta: () => request('/papers/meta')
};
