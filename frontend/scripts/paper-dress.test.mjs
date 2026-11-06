#!/usr/bin/env node
/**
 * Display-dressing tests against the verified Outputs census:
 * original baked-in numbers (plain, bold, II-, A-/B-, stems, headers,
 * Answer/Solution-for lines) must never leak past generated Q-numbers.
 * Run: node --test scripts/paper-dress.test.mjs
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { dressQuestion, dressSolution, isMissingSolutionText } from '../src/lib/paperDress.js';
import { toRoman } from '../src/lib/numbering.js';

const T = (html) => ({ kind: 'text', html });
const F = (url) => ({ kind: 'fig', url });

describe('dressQuestion singles', () => {
	it('bare <ol> stem (N==1) gains the generated start', () => {
		const out = dressQuestion([T('<ol>\n<li>A block rests.</li>\n</ol>')], { numbers: [5] });
		assert.match(out[0].html, /^<ol start="5">/);
	});
	it('<ol start="8"> stem restarts at the generated number', () => {
		const out = dressQuestion([T('<ol start="8">\n<li>A block rests.</li>\n</ol>')], { numbers: [5] });
		assert.match(out[0].html, /^<ol start="5">/);
		assert.doesNotMatch(out[0].html, /start="8"/);
	});
	it('bold II-/B- lead numbers stripped as text', () => {
		assert.equal(
			dressQuestion([T('<p><strong>18.</strong> A container.</p>')], { numbers: [7] })[0].html,
			'<p>A container.</p>');
		assert.equal(
			dressQuestion([T('<p>II-1. An ammeter.</p>')], { numbers: [3] })[0].html,
			'<p>An ammeter.</p>');
	});
	it('bare stems untouched; decimals safe; input never mutated', () => {
		const seg = T('<p>The velocity graph.</p>');
		assert.equal(dressQuestion([seg], { numbers: [1] })[0].html, '<p>The velocity graph.</p>');
		assert.equal(dressQuestion([T('<p>3.16 is the value.</p>')], { numbers: [2] })[0].html,
			'<p>3.16 is the value.</p>');
		assert.equal(seg.html, '<p>The velocity graph.</p>');
	});
});

describe('dressQuestion passages', () => {
	const stems = () => [
		T('<p>Paragraph for Question Nos. 33 to 34:</p> <p>The pipes flow.</p>'),
		F('/fig.png'),
		T('<ol start="33"> <li>First sub</li> </ol>'),
		T('<ol start="34"> <li>Second sub</li> </ol>')
	];
	it('colon header dropped, stems relabelled in document order', () => {
		const out = dressQuestion(stems(), { numbers: [2, 3], para: { a: 33, b: 34, valid: true } });
		assert.doesNotMatch(out[0].html, /Paragraph for Question/);
		assert.match(out[0].html, /The pipes flow/);
		assert.match(out[2].html, /start="2"/);
		assert.match(out[3].html, /start="3"/);
		assert.doesNotMatch(out.filter((s) => s.html).map((s) => s.html).join(' '), /start="33"|start="34"/);
	});
	it('no-colon and bare PARAGRAPH headers dropped too', () => {
		const a = dressQuestion([T('<p>Paragraph for Question Nos. 14 and 15 A uniform rod.</p>')],
			{ numbers: [4, 5], para: { a: 14, b: 15, valid: true } });
		assert.doesNotMatch(a[0].html, /Paragraph for Question/);
		const b = dressQuestion([T('<p>PARAGRAPH-I</p><p>A square plate.</p>')],
			{ numbers: [6, 7], para: { a: 31, b: 32, valid: true } });
		assert.doesNotMatch(b[0].html, /PARAGRAPH/);
	});
	it('glued bold sub-stems relabelled, others untouched', () => {
		const out = dressQuestion(
			[T('<p>PARAGRAPH-I passage <strong>31.</strong> first <strong>32.</strong> second</p>')],
			{ numbers: [2, 3], para: { a: 31, b: 32, valid: true } });
		assert.match(out[0].html, /Q2\./);
		assert.match(out[0].html, /Q3\./);
		assert.doesNotMatch(out[0].html, /31\.|32\./);
	});
	it('options <ol> without original stems left alone', () => {
		const out = dressQuestion([T('<ol> <li>opts</li> </ol>'), T('<ol start="33"> <li>Stem</li> </ol>')],
			{ numbers: [9], para: { a: 33, b: 33, valid: true } });
		assert.match(out[0].html, /^<ol> <li>opts/);
		assert.match(out[1].html, /start="9"/);
	});
});

describe('dressSolution', () => {
	it('relabels Answer and math-mode Solution-for in order, incl. prefixes', () => {
		const enc = (s) => encodeURIComponent(s);
		const segs = [T(`<p><strong>Answer: A-01) A, C</strong></p><p><span class="pl-math" data-tex="${enc('\\underline{\\textbf{Solution for A-01}}')}"></span></p>`)];
		const out = dressSolution(segs, { numbers: [4] });
		assert.match(out[0].html, /Answer: Q4\)/);
		assert.match(out[0].html, /Solution%20for%20Q4/);
		assert.doesNotMatch(out[0].html, /A-01/);
	});
	it('leaves extras alone when numbers run out', () => {
		const out = dressSolution([T('<p><strong>Answer: 1) A</strong></p><p><strong>Answer: 2) B</strong></p>')], { numbers: [5] });
		assert.match(out[0].html, /Answer: Q5\)/);
		assert.match(out[0].html, /Answer: 2\)/);
	});
	it('detects No-solution bodies in both wrappings', () => {
		assert.equal(isMissingSolutionText([T('<p>No solution provided.</p>')]), true);
		assert.equal(isMissingSolutionText([T('<p><em>No solution provided.</em></p>')]), true);
		assert.equal(isMissingSolutionText([T('<p><strong>Answer: 30) 3</strong></p><p>Real text.</p>')]), false);
	});
});

describe('toRoman', () => {
	it('numbers passages I, II, III...', () => {
		assert.equal([1, 2, 3, 4, 9].map(toRoman).join(','), 'I,II,III,IV,IX');
	});
});
