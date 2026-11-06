#!/usr/bin/env node
/**
 * Display-dressing tests against the verified Outputs census:
 * original baked-in numbers (plain, bold, II-, A-/B-, stems, headers,
 * Answer/Solution-for lines) must never leak past generated Q-numbers.
 * Run: node --test scripts/paper-dress.test.mjs
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { dressQuestion, dressSolution, isMissingSolutionText, extractAnswerKeys } from '../src/lib/paperDress.js';
import { toRoman } from '../src/lib/numbering.js';
import { sectionMeta } from '../src/lib/sectionMeta.js';
import { splitTopBlocks } from '../src/lib/flowsplit.js';

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
	it('strips Answer paragraphs, relabels math Solution-for in order', () => {
		const enc = (s) => encodeURIComponent(s);
		const segs = [T(`<p><strong>Answer: A-01) A, C</strong></p><p><span class="pl-math" data-tex="${enc('\\underline{\\textbf{Solution for A-01}}')}"></span></p><p>Work shown.</p>`)];
		const out = dressSolution(segs, { numbers: [4] });
		const html = out.map((s) => s.html || '').join(' ');
		assert.doesNotMatch(html, /Answer:/);
		assert.match(html, /Solution%20for%20Q4/);
		assert.match(html, /Work shown/);
	});
	it('strips every repeated Answer block in group solutions', () => {
		const out = dressSolution([T('<p><strong>Answer: 33) A</strong></p><p>Sol 33.</p><p><strong>Answer: 34) B</strong></p><p>Sol 34.</p>')], { numbers: [2, 3] });
		const html = out.map((s) => s.html || '').join(' ');
		assert.doesNotMatch(html, /Answer:/);
		assert.match(html, /Sol 33/);
		assert.match(html, /Sol 34/);
	});
	it('extracts filed keys in block order', () => {
		assert.deepEqual(extractAnswerKeys([T('<p><strong>Answer: A-01) A, C</strong></p>')]), ['A, C']);
		assert.deepEqual(
			extractAnswerKeys([T('<p><strong>Answer: 33) A</strong></p>'), T('<p><strong>Answer: 34) 4.00</strong></p>')]),
			['A', '4.00']);
		assert.deepEqual(extractAnswerKeys([T('<p>No key here.</p>')]), []);
	});
});

describe('splitTopBlocks', () => {
	it('splits sequential paragraphs, keeps lists whole', () => {
		assert.deepEqual(
			splitTopBlocks('<p>One.</p><p>Two.</p>'),
			['<p>One.</p>', '<p>Two.</p>']);
		assert.deepEqual(
			splitTopBlocks('<ol start="33"> <li>A</li> <li>B</li> </ol>'),
			['<ol start="33"> <li>A</li> <li>B</li> </ol>']);
	});
	it('does not split inside nested lists or tables', () => {
		const nested = '<ol> <li>Stem <p>A) one</p> <p>B) two</p> </li> </ol><p>After.</p>';
		assert.deepEqual(splitTopBlocks(nested), ['<ol> <li>Stem <p>A) one</p> <p>B) two</p> </li> </ol>', '<p>After.</p>']);
	});
	it('ignores void elements and keeps stray text', () => {
		assert.deepEqual(splitTopBlocks('<p>A <img src="x"> B.</p>'), ['<p>A <img src="x"> B.</p>']);
		assert.deepEqual(splitTopBlocks('bare text'), ['bare text']);
		assert.deepEqual(splitTopBlocks(''), []);
	});
});
