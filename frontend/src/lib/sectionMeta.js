/**
 * Section descriptions for the question sheet, in the JEE convention:
 * SECTION–I + (FULL TYPE NAME) + instruction bullets. Pure, tested.
 * Deliberately mark-free: no +/− marks, no totals — the builder does
 * not own marking schemes.
 */

const WORDS = ['ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE', 'TEN'];
const wordOf = (n) => (Number.isInteger(n) && n >= 0 && n < WORDS.length ? WORDS[n] : String(n));

const qword = (n) => (n === 1 ? 'question' : 'questions');

/**
 * @param atype raw section type (scq, par-scq, ...)
 * @param nq number of generated questions in the section
 * @param nstems number of blocks (passage stems) in the section
 */
export function sectionMeta(atype, nq = 0, nstems = 0) {
	const t = String(atype ?? 'unknown').toLowerCase();
	switch (t) {
		case 'scq':
			return {
				kind: 'SINGLE CORRECT ANSWER TYPE',
				lines: [
					`This section contains ${wordOf(nq)} (${String(nq).padStart(2, '0')}) ${qword(nq)}.`,
					'Each question has FOUR options (A), (B), (C) and (D). ONLY ONE of these four options is the correct answer.'
				]
			};
		case 'msq':
			return {
				kind: 'ONE OR MORE CORRECT ANSWER TYPE',
				lines: [
					`This section contains ${wordOf(nq)} (${String(nq).padStart(2, '0')}) ${qword(nq)}.`,
					'Each question has FOUR options (A), (B), (C) and (D). ONE OR MORE THAN ONE of these four option(s) is(are) correct.'
				]
			};
		case 'int':
			return {
				kind: 'INTEGER ANSWER TYPE',
				lines: [
					`This section contains ${wordOf(nq)} (${String(nq).padStart(2, '0')}) ${qword(nq)}.`,
					'The answer to each question is a SINGLE DIGIT INTEGER ranging from 0 TO 9, BOTH INCLUSIVE.'
				]
			};
		case 'num':
			return {
				kind: 'NUMERICAL VALUE TYPE',
				lines: [
					`This section contains ${wordOf(nq)} (${String(nq).padStart(2, '0')}) ${qword(nq)}.`,
					'The answer to each question is a NUMERICAL VALUE.'
				]
			};
		case 'mtx':
			return {
				kind: 'MATCHING ANSWER TYPE',
				lines: [
					`This section contains ${wordOf(nq)} (${String(nq).padStart(2, '0')}) ${qword(nq)}.`,
					'Match the entries across the lists/columns and choose the option with the correct combination.'
				]
			};
		default:
			if (t.startsWith('par-')) {
				const stems = Math.max(nstems, 1);
				return {
					kind: 'PARAGRAPH QUESTIONS',
					lines: [
						`This section contains ${wordOf(stems)} (${String(stems).padStart(2, '0')}) question stem${stems === 1 ? '' : 's'} and ${wordOf(nq)} (${String(nq).padStart(2, '0')}) ${qword(nq)} in all.`,
						'Read each passage carefully and answer its questions independently.'
					]
				};
			}
			return {
				kind: 'GENERAL QUESTIONS',
				lines: [`This section contains ${wordOf(nq)} (${String(nq).padStart(2, '0')}) ${qword(nq)}. Answer each as directed.`]
			};
	}
}
