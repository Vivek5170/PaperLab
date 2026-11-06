/**
 * In-memory question-detail cache (never persisted). Builder previews and
 * solution views share one fetch per question per session instead of each
 * component refetching. Failures are NOT cached — retry refetches.
 */
import { api } from './api.js';

const cache = new Map();

const key = (paperId, number) => `${paperId}::${String(number)}`;

export function getQuestionDetail(paperId, number) {
	const k = key(paperId, number);
	if (!cache.has(k)) {
		cache.set(
			k,
			api.getQuestion(paperId, number).catch((e) => {
				cache.delete(k);
				throw e;
			})
		);
	}
	return cache.get(k);
}

export function dropQuestionDetail(paperId, number) {
	cache.delete(key(paperId, number));
}
