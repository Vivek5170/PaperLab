#!/usr/bin/env node
/**
 * Phase 1 unit tests: paragraph parsing, answer-type normalization,
 * cart model ops. Run: node --test frontend/scripts/cart-model.test.mjs
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { parseParagraphRange } from '../src/lib/paragraph.js';
import { normalizeAnswerType } from '../src/lib/qtypes.js';
import {
	createCart, addItem, removeItem, validateStore, toCartItem
} from '../src/lib/cartModel.js';

const Q = (paperId, number, extra = {}) => ({
	paperId, number, qtype: 'scq', preview: 'p', thumb: null, ...extra
});

describe('parseParagraphRange', () => {
	it('plain ids are not paragraphs', () => {
		for (const n of ['1', '8', '15a', 'A-01']) {
			const r = parseParagraphRange(n, 'scq');
			assert.equal(r.isParagraph, false);
			assert.equal(r.count, 1);
			assert.equal(r.warning, null);
		}
	});
	it('bare range is valid', () => {
		const r = parseParagraphRange('31-32_paragraph', 'par-scq');
		assert.equal(r.isParagraph, true);
		assert.deepEqual([r.a, r.b, r.count, r.valid], [31, 32, 2, true]);
	});
	it('namespaced id recognized via suffix', () => {
		const r = parseParagraphRange('B-31-32_paragraph', 'par-scq');
		assert.equal(r.isParagraph, true);
		assert.equal(r.valid, true);
		assert.equal(r.count, 2);
	});
	it('multi-sub range counts correctly', () => {
		const r = parseParagraphRange('15-17_paragraph', 'par-msq');
		assert.equal(r.count, 3);
		assert.equal(r.valid, true);
	});
	it('reversed range warns and collapses to one', () => {
		const r = parseParagraphRange('32-31_paragraph', 'par-scq');
		assert.equal(r.isParagraph, true);
		assert.equal(r.valid, false);
		assert.equal(r.count, 1);
		assert.match(r.warning, /reversed/);
	});
	it('oversized range warns (bound mirrors render.py a<b<=a+12)', () => {
		const r = parseParagraphRange('1-20_paragraph', 'par-scq');
		assert.equal(r.valid, false);
		assert.match(r.warning, /too large/);
		assert.equal(r.count, 1);
	});
	it('paragraph hint without valid range warns', () => {
		const r = parseParagraphRange('mystery_paragraph', 'unknown');
		assert.equal(r.isParagraph, true);
		assert.equal(r.valid, false);
		assert.match(r.warning, /Unrecognized paragraph id/);
	});
	it('par qtype without range warns instead of silent normal', () => {
		const r = parseParagraphRange('8', 'par-scq');
		assert.equal(r.valid, false);
		assert.match(r.warning, /no paragraph range/);
	});
});

describe('normalizeAnswerType', () => {
	it('strips par- prefix, preserves raw separately', () => {
		assert.equal(normalizeAnswerType('par-scq'), 'scq');
		assert.equal(normalizeAnswerType('par-msq'), 'msq');
		assert.equal(normalizeAnswerType('par-int'), 'int');
		assert.equal(normalizeAnswerType('par-num'), 'num');
		assert.equal(normalizeAnswerType('par-mtx'), 'mtx');
		assert.equal(normalizeAnswerType('scq'), 'scq');
		assert.equal(normalizeAnswerType('unknown'), 'unknown');
		assert.equal(normalizeAnswerType(null), 'unknown');
	});
	it('par-mix stays distinct', () => {
		assert.equal(normalizeAnswerType('par-mix'), 'mix');
	});
});

describe('cartModel', () => {
	it('add dedupes by identity', () => {
		let c = createCart('t');
		let r = addItem(c, Q(11, '8'));
		assert.equal(r.added, true);
		r = addItem(r.cart, Q(11, '8'));
		assert.equal(r.added, false);
		assert.equal(r.reason, 'duplicate');
		assert.equal(r.cart.items.length, 1);
	});
	it('rejects invalid identity', () => {
		const c = createCart('t');
		const r = addItem(c, { paperId: null, number: '' });
		assert.equal(r.added, false);
	});
	it('remove + clear semantics', () => {
		let c = createCart('t');
		c = addItem(c, Q(11, '8')).cart;
		const r = removeItem(c, 11, '8');
		assert.equal(r.removed, true);
		assert.equal(r.cart.items.length, 0);
		assert.equal(removeItem(r.cart, 11, '8').removed, false);
	});
	it('validateStore repairs dupes and bad rows, keeps snapshots small', () => {
		const { ok, store } = validateStore({
			version: 1,
			activeId: 'x',
			carts: [{
				id: 'c1', name: 'A', createdAt: 't', updatedAt: 't',
				items: [Q(11, '8'), Q(11, '8'), { paperId: 1 }, { paperId: 2, number: '3', qtype: 'scq', preview: 'x'.repeat(5000) }]
			}]
		});
		assert.equal(ok, true);
		assert.equal(store.carts[0].items.length, 2);
		assert.ok(store.carts[0].items[1].preview.length <= 300);
	});
	it('validateStore falls back on garbage', () => {
		const { ok, store } = validateStore(null);
		assert.equal(ok, false);
		assert.equal(store.carts.length, 1);
	});
	it('toCartItem drops segments/HTML (never stores rendered data)', () => {
		const it = toCartItem({
			paperId: 11, number: '8', qtype: 'scq',
			preview: '<p>hi</p>', thumb: '/api/x',
			question: [{ kind: 'text', html: '<p>hi</p>' }]
		});
		assert.equal(it.preview, '<p>hi</p>');
		assert.ok(!('question' in it));
		assert.ok(!('segments' in it));
	});
});
