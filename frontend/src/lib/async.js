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
