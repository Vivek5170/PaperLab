/**
 * Single numbering source for the builder (pure, no Svelte/store deps).
 *
 * `assignNumbers()` receives blocks flattened in ACTUAL document order
 * (paper: section order then block order; assignment: flat block order)
 * and owns every generated number. BuilderBlock, KeyTable and
 * SolutionsList all consume this one result — no component may number
 * anything on its own.
 *
 * Paragraph groups stay indivisible: one block consumes k consecutive
 * numbers (k from parseParagraphRange, bound-mirrored with render.py).
 * Unrecognized ids collapse to one number and surface a warning; they
 * never break numbering and never drop the block from key/solutions.
 */
import { parseParagraphRange } from './paragraph.js';

/**
 * @param ordered Array of {blockId, paperId, number, qtype} in document order.
 * @returns {byBlock: {blockId:[n,...]}, byNumber: {n:{blockId,subIndex}},
 *          total, warnings: [{blockId, warning}]}
 */
export function assignNumbers(ordered) {
	const byBlock = {};
	const byNumber = {};
	const warnings = [];
	let n = 0;
	for (const b of ordered ?? []) {
		if (!b || !b.blockId) continue;
		const r = parseParagraphRange(b.number, b.qtype);
		if (r.warning) warnings.push({ blockId: b.blockId, warning: r.warning });
		const count = r.valid ? r.count : 1;
		const nums = [];
		for (let i = 0; i < count; i++) {
			n += 1;
			nums.push(n);
			byNumber[n] = { blockId: b.blockId, subIndex: i };
		}
		byBlock[b.blockId] = nums;
	}
	return { byBlock, byNumber, total: n, warnings };
}

/**
 * Flatten a draft to document order, skipping dangling refs.
 * @returns Array of {...block, blockId, sectionId} in reading order.
 */
export function flattenDraft(draft) {
	const out = [];
	for (const s of draft?.sections ?? []) {
		for (const bid of s?.blockIds ?? []) {
			const b = draft?.blocks?.[bid];
			if (b) out.push({ ...b, blockId: bid, sectionId: s.id });
		}
	}
	return out;
}

/** I, II, III... for passage order. */
export function toRoman(n) {
	const table = [[1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'], [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']];
	let out = '';
	let v = Math.max(1, Math.min(3999, n | 0));
	for (const [val, sym] of table) while (v >= val) { out += sym; v -= val; }
	return out;
}

/** "Q5" or "Q5–Q7" label for a block's numbers. */
export function numberLabel(nums) {
	if (!nums || nums.length === 0) return '—';
	if (nums.length === 1) return `Q${nums[0]}`;
	return `Q${nums[0]}–Q${nums[nums.length - 1]}`;
}
