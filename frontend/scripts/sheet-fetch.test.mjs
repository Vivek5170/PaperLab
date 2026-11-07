import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { backoffDelay, pool, sleep, withTimeout, isUnsettled } from '../src/lib/async.js';
import { BULK_SEED_MIN, bulkSeedPlan, applyBulkSeed } from '../src/lib/bulkSeed.js';

describe('sleep', () => {
	it('resolves after ~0ms without hanging', async () => {
		const t0 = Date.now();
		await sleep(0);
		await sleep(-5);
		assert.ok(Date.now() - t0 < 1000);
	});
});

describe('backoffDelay', () => {
	it('grows exponentially and honours the cap', () => {
		const rand = () => 0.999999; // worst case: full backoff, no jitter luck
		assert.equal(backoffDelay(0, 1000, 8000, rand), 999);
		assert.equal(backoffDelay(1, 1000, 8000, rand), 1999);
		assert.equal(backoffDelay(2, 1000, 8000, rand), 3999);
		assert.equal(backoffDelay(3, 1000, 8000, rand), 7999);
		assert.equal(backoffDelay(4, 1000, 8000, rand), 8000); // capped
		assert.equal(backoffDelay(10, 1000, 8000, rand), 8000); // stays capped
	});
	it('jitter keeps values within [0, grown]', () => {
		assert.equal(backoffDelay(2, 1000, 8000, () => 0), 0);
		for (let i = 0; i < 20; i++) {
			const d = backoffDelay(1, 1000, 8000);
			assert.ok(d >= 0 && d <= 2000);
		}
	});
	it('negative attempts behave like attempt 0', () => {
		assert.equal(backoffDelay(-3, 1000, 8000, () => 0.5), 500);
	});
});

describe('pool', () => {
	it('runs everything unbounded when limit <= 0', async () => {
		const seen = [];
		const out = await pool([1, 2, 3], 0, async (x) => {
			seen.push(x);
			return x * 2;
		});
		assert.deepEqual(seen.sort(), [1, 2, 3]);
		assert.deepEqual(out, [
			{ ok: true, value: 2 },
			{ ok: true, value: 4 },
			{ ok: true, value: 6 }
		]);
	});
	it('caps in-flight work and keeps order', async () => {
		let live = 0;
		let peak = 0;
		const out = await pool([1, 2, 3, 4, 5], 2, async (x) => {
			live++;
			peak = Math.max(peak, live);
			await sleep(5);
			live--;
			return x;
		});
		assert.ok(peak <= 2, `peak in-flight ${peak} exceeds limit 2`);
		assert.deepEqual(out.map((r) => r.value), [1, 2, 3, 4, 5]);
		assert.ok(out.every((r) => r.ok));
	});
	it('captures per-item errors without rejecting', async () => {
		const out = await pool(['a', 'b'], 2, async (x) => {
			if (x === 'b') throw new Error('nope');
			return x;
		});
		assert.equal(out[0].ok, true);
		assert.equal(out[1].ok, false);
		assert.match(String(out[1].error?.message ?? out[1].error), /nope/);
	});
	it('handles empty input', async () => {
		assert.deepEqual(await pool([], 3, async () => 1), []);
	});
});

describe('isUnsettled (watchdog predicate)', () => {
	it('flags only stale loading/waiting entries', () => {
		const now = 100000;
		assert.equal(isUnsettled(undefined, now), false);
		assert.equal(isUnsettled({ ready: true }, now), false);
		assert.equal(isUnsettled({ error: 'x' }, now), false);
		assert.equal(isUnsettled({ loading: true, at: now - 1000 }, now), false);
		assert.equal(isUnsettled({ loading: true, at: now - 36000 }, now), true);
		assert.equal(isUnsettled({ waiting: true, at: now - 40000 }, now), true);
		assert.equal(isUnsettled({ loading: true }, now, 1000), true); // missing `at` counts as stale
	});
});

describe('withTimeout (still)', () => {
	it('passes fast values through', async () => {
		assert.equal(await withTimeout(Promise.resolve(7), 500), 7);
	});
});

describe('bulkSeedPlan', () => {
	const E = (paperId, number) => ({ blockId: `${paperId}:${number}`, paperId, number });
	it('groups 3+ per paper into bulk, skips the rest', () => {
		assert.equal(BULK_SEED_MIN, 3);
		const missing = [E(1, 'a'), E(1, 'b'), E(2, 'x'), E(1, 'c')];
		assert.deepEqual(bulkSeedPlan(missing), {
			bulk: [{ paperId: 1, numbers: ['a', 'b', 'c'] }]
		});
	});
	it('ignores entries without paperId, handles empties', () => {
		assert.deepEqual(bulkSeedPlan([]), { bulk: [] });
		assert.deepEqual(bulkSeedPlan([{ blockId: 'z' }]), { bulk: [] });
		assert.deepEqual(bulkSeedPlan([E(9, 'a'), E(9, 'b')]), { bulk: [] });
	});
});

describe('applyBulkSeed', () => {
	it('seeds matches, returns seeded numbers, skips absent', () => {
		const calls = [];
		const seeded = applyBulkSeed(
			(pid, n, item) => calls.push([pid, n, item]),
			11,
			[{ number: '8' }, { number: '9', extra: 1 }],
			['8', '9', 'zzz']
		);
		assert.deepEqual(seeded, ['8', '9']);
		assert.deepEqual(calls.map(([p, n]) => [p, n]), [[11, '8'], [11, '9']]);
		assert.equal(calls[1][2].extra, 1);
	});
	it('matches numeric and string question ids', () => {
		const calls = [];
		applyBulkSeed((pid, n, item) => calls.push([pid, n]), 5, [{ number: 33 }], ['33']);
		assert.deepEqual(calls, [[5, '33']]);
	});
	it('tolerates empty bulk responses', () => {
		const calls = [];
		assert.deepEqual(applyBulkSeed((...a) => calls.push(a), 5, null, ['x']), []);
		assert.deepEqual(applyBulkSeed((...a) => calls.push(a), 5, [], ['x']), []);
		assert.equal(calls.length, 0);
	});
});
