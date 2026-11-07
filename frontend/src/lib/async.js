/**
 * Small async helpers (no deps, node-testable).
 */

/**
 * Race a promise against a timeout. The underlying work is NOT cancelled
 * (the cache keeps it); callers just stop waiting and can show Retry.
 */
export function withTimeout(promise, ms, message = 'Timed out') {
	let timer = null;
	const timeout = new Promise((_, reject) => {
		timer = setTimeout(() => reject(new Error(message)), ms);
	});
	return Promise.race([
		Promise.resolve(promise).finally(() => clearTimeout(timer)),
		timeout
	]);
}

/** Resolve after ms milliseconds. */
export function sleep(ms) {
	return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
}

/**
 * Bounded exponential backoff: base * 2^attempt plus full jitter,
 * capped at cap. attempt 0 waits ~[0, base]. `rand` is injectable so
 * tests stay deterministic (defaults to Math.random).
 */
export function backoffDelay(attempt, base = 1000, cap = 8000, rand = Math.random) {
	const grown = base * 2 ** Math.max(0, Math.floor(attempt));
	return Math.min(cap, Math.floor(rand() * grown));
}

/**
 * Run async fn over items with at most `limit` in flight. Never rejects
 * early: resolves to per-item {ok, value} / {ok: false, error} in order.
 * limit <= 0 means unbounded (Promise.all behaviour).
 */
export async function pool(items, limit, fn) {
	const list = [...(items ?? [])];
	if (list.length === 0) return [];
	if (!(limit > 0)) {
		const settled = await Promise.allSettled(list.map((it) => fn(it)));
		return settled.map((s) =>
			s.status === 'fulfilled' ? { ok: true, value: s.value } : { ok: false, error: s.reason });
	}
	const out = new Array(list.length);
	let next = 0;
	const workers = Array.from(
		{ length: Math.min(limit, list.length) },
		async () => {
			while (next < list.length) {
				const i = next++;
				try {
					out[i] = { ok: true, value: await fn(list[i], i) };
				} catch (error) {
					out[i] = { ok: false, error };
				}
			}
		}
	);
	await Promise.all(workers);
	return out;
}
