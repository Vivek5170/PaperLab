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
import { withTimeout } from '../src/lib/async.js';
import { parseParagraphRange } from '../src/lib/paragraph.js';

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
	it('strips Answer paragraphs, drops first Solution-for label (sheet heads it)', () => {
		const enc = (s) => encodeURIComponent(s);
		const segs = [T(`<p><strong>Answer: A-01) A, C</strong></p><p><span class="pl-math" data-tex="${enc('\\underline{\\textbf{Solution for A-01}}')}"></span></p><p>Work shown.</p>`)];
		const out = dressSolution(segs, { numbers: [4] });
		const html = out.map((s) => s.html || '').join(' ');
		assert.doesNotMatch(html, /Answer:/);
		assert.doesNotMatch(html, /Solution for/);
		assert.match(html, /Work shown/);
	});
	it('turns per-sub-solution labels into Solution Qn sub-headings', () => {
		const enc = (s) => encodeURIComponent(s);
		const L = (qn) => `<p><span class="pl-math" data-tex="${enc(`\\underline{\\textbf{Solution for ${qn}}}`)}"></span></p>`;
		const segs = [T(`<p><strong>Answer: 33) A</strong></p>${L('33')}<p>Sol 33.</p><p><strong>Answer: 34) B</strong></p>${L('34')}<p>Sol 34.</p>`)];
		const out = dressSolution(segs, { numbers: [7, 8] });
		const html = out.map((s) => s.html || '').join(' ');
		assert.doesNotMatch(html, /Answer:/);
		assert.doesNotMatch(html, /Solution for/);
		assert.match(html, /<p class="subsolhead">Solution Q7<\/p>/);
		assert.match(html, /<p class="subsolhead">Solution Q8<\/p>/);
		assert.doesNotMatch(html, /sol-div/);
		assert.match(html, /Sol 33/);
		assert.match(html, /Sol 34/);
	});
	it('single-number blocks still drop the label; extras become dividers', () => {
		const enc = (s) => encodeURIComponent(s);
		const L = (qn) => `<p><span class="pl-math" data-tex="${enc(`\\underline{\\textbf{Solution for ${qn}}}`)}"></span></p>`;
		const segs = [T(`${L('33')}<p>Only.</p>${L('33')}<p>More.</p>`)];
		const out = dressSolution(segs, { numbers: [7] });
		const html = out.map((s) => s.html || '').join(' ');
		assert.doesNotMatch(html, /Solution for/);
		assert.doesNotMatch(html, /subsolhead/);
		assert.match(html, /<hr class="sol-div">/);
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

describe('splitTopBlocks extras', () => {
	it('emits bare <hr> and figure blocks; survives > in attributes', () => {
		assert.deepEqual(splitTopBlocks('<p>A.</p><hr><p>B.</p>'), ['<p>A.</p>', '<hr>', '<p>B.</p>']);
		assert.deepEqual(splitTopBlocks('<figure><img src="x"></figure><p>Cap.</p>'), ['<figure><img src="x"></figure>', '<p>Cap.</p>']);
		assert.deepEqual(splitTopBlocks('<p title="a>b">X.</p>'), ['<p title="a>b">X.</p>']);
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

describe('withTimeout', () => {
	it('passes fast values through', async () => {
		assert.equal(await withTimeout(Promise.resolve(7), 500), 7);
	});
	it('rejects slow work instead of hanging', async () => {
		await assert.rejects(withTimeout(new Promise(() => {}), 20, 'slow?'), /slow\?/);
	});
});

describe('paragraph span bound (mirrors render.py a<b<=a+12)', () => {
	it('accepts 1-13 (13 sub-questions), rejects 1-14', () => {
		assert.equal(parseParagraphRange('1-13_paragraph').count, 13);
		assert.equal(parseParagraphRange('1-13_paragraph').valid, true);
		assert.equal(parseParagraphRange('1-14_paragraph').valid, false);
	});
});

describe('glued passage headers', () => {
	it('strips header prefix but keeps body in the same paragraph', async () => {
		const { dressQuestion } = await import('../src/lib/paperDress.js');
		const segs = [{ kind: 'text', html: '<p>Paragraph for Question Nos. 33 to 34: Pitot tube is used in wind tunnels.</p>' }];
		const out = dressQuestion(segs, { numbers: [5, 6], para: { a: 33, b: 34, valid: true } });
		assert.ok(!/Paragraph for Question Nos/i.test(out[0].html), 'header gone: ' + out[0].html);
		assert.ok(/Pitot tube/.test(out[0].html), 'body kept');
	});
	it('drops standalone header paragraphs entirely', async () => {
		const { dressQuestion } = await import('../src/lib/paperDress.js');
		const segs = [
			{ kind: 'text', html: '<p>Paragraph for Question Nos. 33 to 34:</p>' },
			{ kind: 'text', html: '<p>Water is flowing.</p>' }
		];
		const out = dressQuestion(segs, { numbers: [5, 6], para: { a: 33, b: 34, valid: true } });
		assert.ok(!/Paragraph for Question Nos/i.test(out.map(s => s.html ?? '').join(' ')));
	});
});

describe('par section instructions', () => {
	it('names the answer type for par-scq/par-int/par-num/par-msq', async () => {
		const { sectionMeta } = await import('../src/lib/sectionMeta.js');
		assert.match(sectionMeta('par-scq', 4, 2).kind, /SINGLE CORRECT/);
		assert.match(sectionMeta('par-int', 2, 1).lines[1], /SINGLE DIGIT INTEGER/);
		assert.match(sectionMeta('par-num', 2, 1).lines[1], /NUMERICAL VALUE/);
		assert.match(sectionMeta('par-msq', 4, 2).kind, /ONE OR MORE/);
	});
});

describe('math-only solutions are content', () => {
	it('keeps math-only paragraphs after Answer-strip (Q7-Q8 regression)', async () => {
		const { dressSolution } = await import('../src/lib/paperDress.js');
		const math = (tex) => `<p><span class="pl-math" data-tex="${tex}" data-display="0"></span></p>`;
		const segs = [{ kind: 'text', html: `<p><strong>Answer: 33) 6</strong></p>\n${math('Rcal')} \n<p><strong>Answer: 34) 150</strong></p>\n${math('lheat')}` }];
		const out = dressSolution(segs, { numbers: [7, 8] });
		assert.equal(out.length, 1);
		assert.ok(!/Answer:/.test(out[0].html));
		assert.ok(/data-tex/.test(out[0].html), 'math kept');
	});
});

describe('key-only solutions', () => {
	it('dress to zero rows when the filed solution is only Answer lines', async () => {
		const { dressSolution } = await import('../src/lib/paperDress.js');
		const segs = [
			{ kind: 'text', html: '<p>Answer: 33) A</p>' },
			{ kind: 'text', html: '<p>Answer: 34) B</p>' }
		];
		assert.deepEqual(dressSolution(segs, { numbers: [7, 8] }), []);
	});
});

describe('option/stem margin rhythm (measured originals)', () => {
	it('tags A)-led paragraphs pl-opt, leaves prose alone', async () => {
		const { dressQuestion } = await import('../src/lib/paperDress.js');
		const out = dressQuestion([
			{ kind: 'text', html: '<ol start="4"><li>Stem text.</li></ol><p>A) one</p><p><strong>B)</strong> two</p><p>A ball of mass m.</p><p class="keep">C) keep</p>' }
		], { numbers: [4], para: null });
		const html = out.map(s => s.html ?? '').join(' ');
		assert.match(html, /<p class="pl-opt">A\) one<\/p>/);
		assert.match(html, /<p class="pl-opt"><strong>B\)<\/strong> two<\/p>/);
		assert.doesNotMatch(html, /pl-opt">A ball/);
		assert.match(html, /<p class="keep">C\) keep<\/p>/);
	});
});

describe('filed cross-reference leaks (Q.14-15 regression)', () => {
	it('drops standalone (Q…) paras and strips leading markers', async () => {
		const { dressSolution } = await import('../src/lib/paperDress.js');
		const enc = (s) => encodeURIComponent(s);
		const L = (qn) => `<p><span class="pl-math" data-tex="${enc(`\\underline{\\textbf{Solution for ${qn}}}`)}"></span></p>`;
		const segs = [{ kind: 'text', html: `<p><strong>Answer: 14) 20.00</strong></p>${L('14')}<p>(Q.14-15):</p><p><span class="pl-math" data-tex="${enc('J_1')}"></span>...(i)</p><p>(Q.14-15): tail kept</p>` }];
		const out = dressSolution(segs, { numbers: [13, 14] });
		const html = out.map(s => s.html ?? '').join(' ');
		assert.doesNotMatch(html, /Answer:/);
		assert.doesNotMatch(html, /Solution for/);
		assert.doesNotMatch(html, /\(Q\.14-15\)/);
		assert.match(html, /\.\.\.\(i\)/);
		assert.match(html, /<p>tail kept<\/p>/);
	});
	it('strips markers mid-segment, even wrapped in formatting tags', async () => {
		const { dressSolution } = await import('../src/lib/paperDress.js');
		// Exact paper-13 shape: marker rides 3rd in the segment, not first.
		const segs = [{ kind: 'text', html: `<p>x</p><p>y</p><p>(Q.16-17): When</p><p>z</p>` }];
		const html = dressSolution(segs, { numbers: [15, 16] }).map(s => s.html ?? '').join(' ');
		assert.doesNotMatch(html, /\(Q\.16-17\)/);
		assert.match(html, /<p>When<\/p>/);
		const wrapped = [{ kind: 'text', html: `<p>a</p><p><strong>(Q.16-17):</strong> Then</p>` }];
		const html2 = dressSolution(wrapped, { numbers: [15, 16] }).map(s => s.html ?? '').join(' ');
		assert.doesNotMatch(html2, /\(Q\.16-17\)/);
		assert.match(html2, /Then/);
	});
	it('never eats prose that merely mentions Q (no false positives)', async () => {
		const { dressSolution } = await import('../src/lib/paperDress.js');
		const segs = [{ kind: 'text', html: `<p>Q factor of the coil is high.</p><p>The charge Q5 stays.</p><p>See (Q.5) option above.</p>` }];
		const html = dressSolution(segs, { numbers: [1] }).map(s => s.html ?? '').join(' ');
		assert.match(html, /Q factor of the coil is high/);
		assert.match(html, /charge Q5 stays/);
		assert.match(html, /option above/);
	});
	it('drops "Correct answer is (X)" duplicates, keeps lookalike prose', async () => {
		const { dressSolution, isAnswerPara } = await import('../src/lib/paperDress.js');
		assert.ok(isAnswerPara('<p>Correct answer is (C)</p>'));
		assert.ok(!isAnswerPara('<p>Correct Step-by-Step Analysis:</p>'));
		// Exact paper-11 shape: Answer + label + duplicate, nothing else.
		const enc = (s) => encodeURIComponent(s);
		const segs = [{ kind: 'text', html: `<p><strong>Answer: 3) C</strong></p><p><span class="pl-math" data-tex="${enc('\\underline{\\textbf{Solution for 3}}')}"></span></p><p>Correct answer is (C)</p>` }];
		const out = dressSolution(segs, { numbers: [3] });
		assert.deepEqual(out, []);
	});
});
