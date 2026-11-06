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
	removeBlock, restoreBlock, setKeyOverride, sectionAccepts, validateDraft
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
	it('autoGroup: passages go to a Passage section, never typed', () => {
		let d = createDraft('paper');
		d = importBlocks(d, [C(11, '8', 'scq'), C(11, '15-17_paragraph', 'par-scq'), C(11, '33-34_paragraph', 'par-mix'), C(11, '9', 'msq')]).draft;
		d = autoGroup(d).draft;
		const types = d.sections.map((s) => s.atype).sort();
		assert.deepEqual(types, ['msq', 'passage', 'scq']);
		const pas = d.sections.find((s) => s.atype === 'passage');
		assert.equal(pas.blockIds.length, 2);
		assert.ok(!d.sections.some((s) => s.atype === 'par-scq' || s.atype === 'par-mix'));
		// Raw qtype preserved on every block.
		assert.equal(d.blocks[pas.blockIds[0]].qtype, 'par-scq');
		assert.equal(d.blocks[pas.blockIds[1]].qtype, 'par-mix');
	});
	it('passage sections accept any paragraph, refuse singles', () => {
		const p = { id: 's', title: 'P', atype: 'passage', blockIds: [] };
		assert.equal(sectionAccepts(p, { qtype: 'par-mix', number: '33-34_paragraph' }), true);
		assert.equal(sectionAccepts(p, { qtype: 'par-scq', number: '15-17_paragraph' }), true);
		assert.equal(sectionAccepts(p, { qtype: 'scq', number: '8' }), false);
	});
	it('import always regroups: new types gain sections, letters stay positional', () => {
		let d = createDraft('paper');
		d = importBlocks(d, [C(11, '8', 'scq')]).draft;
		assert.deepEqual(d.sections.map((s) => s.atype), ['scq']);
		d = importBlocks(d, [C(11, '9', 'msq'), C(11, '15-17_paragraph', 'par-scq')]).draft;
		assert.deepEqual(d.sections.map((s) => s.atype), ['scq', 'msq', 'passage']);
		assert.equal(d.sections[0].blockIds.length, 1);
		assert.equal(d.sections[2].blockIds.length, 1);
	});
	it('removing the last block of a section prunes it', () => {
		let d = createDraft('paper');
		d = importBlocks(d, [C(11, '8', 'scq'), C(11, '9', 'msq')]).draft;
		const scqBid = d.sections.find((s) => s.atype === 'scq').blockIds[0];
		d = removeBlock(d, scqBid).draft;
		assert.deepEqual(d.sections.map((s) => s.atype), ['msq']);
	});
	it('undo restores the same block id, position and overrides', () => {
		let d = createDraft('paper');
		d = importBlocks(d, [C(11, '8'), C(11, '9')]).draft;
		const [idA, idB] = Object.keys(d.blocks);
		d = setKeyOverride(d, idA, 0, 'B');
		const sid = d.sections[0].id;
		const r = removeBlock(d, idA);
		assert.equal(r.removed, true);
		assert.ok(r.snapshot);
		const u = restoreBlock(r.draft, r.snapshot);
		assert.equal(u.restored, true);
		assert.deepEqual(u.draft.sections[0].blockIds, [idA, idB]);
		assert.equal(u.draft.keyOverride[`${idA}:0`], 'B');
		// Second restore of the same snapshot refuses (id back in use).
		assert.equal(restoreBlock(u.draft, r.snapshot).restored, false);
	});
	it('section gate: normalized match passes, mismatch refuses', () => {
		let d = createDraft('paper');
		d = importBlocks(d, [C(11, '8', 'scq')]).draft;
		const scqBid = d.sections[0].blockIds[0];
		d = addSection(d, { title: 'Manual', atype: 'msq' }).draft;
		const msq = d.sections[d.sections.length - 1];
		assert.equal(sectionAccepts(msq, { qtype: 'par-msq', number: '1' }), true);
		assert.equal(sectionAccepts(msq, { qtype: 'scq', number: '8' }), false);
		const r = moveBlockToSection(d, scqBid, msq.id);
		assert.equal(r.moved, false);
		assert.equal(r.reason, 'type-mismatch');
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
