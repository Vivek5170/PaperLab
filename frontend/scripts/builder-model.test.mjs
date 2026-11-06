#!/usr/bin/env node
/**
 * Phase 2 unit tests: numbering + builder model.
 * Run: node --test frontend/scripts/builder-model.test.mjs
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { assignNumbers, flattenDraft, numberLabel } from '../src/lib/numbering.js';
import {
	createDraft, importBlocks, autoGroup, addSection, deleteSection,
	setSectionAtype, moveSection, moveBlock, moveBlockToSection,
	removeBlock, setKeyOverride, sectionAccepts, validateDraft
} from '../src/lib/builderModel.js';

const B = (blockId, paperId, number, qtype = 'scq') => ({ blockId, paperId, number, qtype });
const C = (paperId, number, qtype = 'scq') => ({ paperId, number, qtype });

describe('assignNumbers', () => {
	it('numbers continuously across blocks', () => {
		const r = assignNumbers([B('a', 11, '8'), B('b', 11, '9')]);
		assert.deepEqual(r.byBlock, { a: [1], b: [2] });
		assert.deepEqual(r.byNumber[2], { blockId: 'b', subIndex: 0 });
		assert.equal(r.total, 2);
	});
	it('paragraph block consumes consecutive numbers, stays one block', () => {
		const r = assignNumbers([B('a', 11, '8'), B('p', 11, '15-17_paragraph', 'par-scq'), B('c', 11, '9')]);
		assert.deepEqual(r.byBlock.p, [2, 3, 4]);
		assert.deepEqual(r.byBlock.c, [5]);
		assert.deepEqual(r.byNumber[3], { blockId: 'p', subIndex: 1 });
		assert.equal(r.total, 5);
	});
	it('namespaced paragraph recognized', () => {
		const r = assignNumbers([B('p', 12, 'B-31-32_paragraph', 'par-num')]);
		assert.deepEqual(r.byBlock.p, [1, 2]);
	});
	it('invalid ranges collapse to one + warn, never drop the block', () => {
		const r = assignNumbers([B('x', 11, '32-31_paragraph', 'par-scq'), B('y', 11, '8')]);
		assert.deepEqual(r.byBlock.x, [1]);
		assert.deepEqual(r.byBlock.y, [2]);
		assert.equal(r.warnings.length, 1);
		assert.equal(r.total, 2);
	});
	it('components share one map (numberLabel)', () => {
		assert.equal(numberLabel([5]), 'Q5');
		assert.equal(numberLabel([2, 3, 4]), 'Q2–Q4');
	});
});

describe('flattenDraft', () => {
	it('flattens in section then block order', () => {
		const d = {
			sections: [{ id: 's1', blockIds: ['b', 'a'] }, { id: 's2', blockIds: ['c'] }],
			blocks: { a: { paperId: 1, number: '1', qtype: 'scq' }, b: { paperId: 1, number: '2', qtype: 'scq' }, c: { paperId: 1, number: '3', qtype: 'scq' } }
		};
		assert.deepEqual(flattenDraft(d).map((x) => x.blockId), ['b', 'a', 'c']);
	});
});

describe('builderModel', () => {
	it('import deep-clones with fresh ids; reimport detects dupes', () => {
		let d = createDraft('paper');
		let r = importBlocks(d, [C(11, '8'), C(11, '15-17_paragraph', 'par-scq')]);
		assert.equal(r.added.length, 2);
		assert.equal(r.skipped.length, 0);
		d = r.draft;
		const ids = Object.keys(d.blocks);
		assert.equal(new Set(ids).size, 2);
		// Mutating the cart item afterwards cannot touch the draft.
		r = importBlocks(d, [C(11, '8'), C(11, '9')]);
		assert.equal(r.added.length, 1);
		assert.deepEqual(r.skipped, [{ paperId: 11, number: '8' }]);
		// Explicit confirmation adds the dupe.
		r = importBlocks(r.draft, [C(11, '8')], { allowDupes: true });
		assert.equal(r.added.length, 1);
		assert.equal(Object.keys(r.draft.blocks).length, 4);
	});
	it('autoGroup merges par-* into normalized sections, keeps raw qtype', () => {
		let d = createDraft('paper');
		d = importBlocks(d, [C(11, '8', 'scq'), C(11, '15-17_paragraph', 'par-scq'), C(11, '9', 'msq')]).draft;
		d = autoGroup(d).draft;
		assert.equal(d.sections.length, 2);
		const scq = d.sections.find((s) => s.atype === 'scq');
		assert.equal(scq.blockIds.length, 2);
		assert.equal(d.blocks[scq.blockIds[1]].qtype, 'par-scq');
		assert.ok(!d.sections.some((s) => s.atype === 'par-scq'));
	});
	it('section gate: normalized match passes, mismatch refuses', () => {
		let d = createDraft('paper');
		d = addSection(d, { title: 'S1', atype: 'scq' }).draft;
		d = addSection(d, { title: 'S2', atype: 'msq' }).draft;
		const [s1, s2] = d.sections.slice(-2);
		assert.equal(sectionAccepts(s2, { qtype: 'par-msq' }), true);
		assert.equal(sectionAccepts(s2, { qtype: 'scq' }), false);
		const r1 = importBlocks(d, [C(11, '8', 'scq')], { sectionId: s1.id });
		const r2 = moveBlockToSection(r1.draft, r1.added[0], s2.id);
		assert.equal(r2.moved, false);
		assert.equal(r2.reason, 'type-mismatch');
	});
	it('reorder never regenerates ids; overrides follow blocks', () => {
		let d = createDraft('paper');
		d = importBlocks(d, [C(11, '8'), C(11, '9')]).draft;
		const [idA, idB] = Object.keys(d.blocks);
		d = setKeyOverride(d, idA, 0, 'B');
		d = moveBlock(d, idB, -1).draft;
		assert.deepEqual(Object.keys(d.blocks), [idA, idB]);
		assert.equal(d.keyOverride[`${idA}:0`], 'B');
		d = removeBlock(d, idA).draft;
		assert.ok(!(`${idA}:0` in d.keyOverride));
	});
	it('delete/retype section only when empty', () => {
		let d = createDraft('paper');
		d = addSection(d, { title: 'S', atype: 'scq' }).draft;
		const sid = d.sections[d.sections.length - 1].id;
		d = importBlocks(d, [C(11, '8')], { sectionId: sid }).draft;
		assert.equal(deleteSection(d, sid).deleted, false);
		assert.equal(setSectionAtype(d, sid, 'msq').changed, false);
	});
	it('moveSection reorders sections', () => {
		let d = createDraft('paper');
		d = addSection(d, { title: 'A', atype: 'scq' }).draft;
		d = addSection(d, { title: 'B', atype: 'msq' }).draft;
		d = moveSection(d, 1, 0).draft;
		assert.deepEqual(d.sections.map((s) => s.title), ['B', 'A']);
	});
	it('validateDraft repairs without regenerating surviving ids', () => {
		const { draft } = validateDraft({
			mode: 'paper', title: 'T',
			sections: [{ id: 's1', title: 'S', atype: 'scq', blockIds: ['b1', 'ghost'] }],
			blocks: { b1: { paperId: 11, number: '8', qtype: 'scq' } },
			keyOverride: { 'b1:0': 'A', 'ghost:0': 'B' }
		});
		assert.deepEqual(draft.sections[0].blockIds, ['b1']);
		assert.deepEqual(draft.keyOverride, { 'b1:0': 'A' });
		assert.ok(draft.blocks.b1);
	});
});
