#!/usr/bin/env node
/**
 * Render smoke test: SSR-renders every question's segments and fails loudly
 * on render throws or structurally empty table cells. Catches the class of
 * bug where the API shape and the Svelte template disagree.
 *
 * Usage: npm run smoke [-- --api http://127.0.0.1:8000]
 * Requires: the backend API running.
 */
import { compile } from 'svelte/compiler';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const apiIdx = process.argv.indexOf('--api');
const BASE = (apiIdx === -1 ? null : process.argv[apiIdx + 1]) || 'http://127.0.0.1:8000';

async function get(p) {
	const r = await fetch(BASE + p);
	if (!r.ok) throw new Error(`GET ${p}: ${r.status}`);
	return r.json();
}

function checkShape(segs, where, problems) {
	for (const s of segs) {
		if (!s || typeof s.kind !== 'string') {
			problems.push(`${where}: segment without kind`);
			continue;
		}
		if (s.kind === 'text' && typeof s.html !== 'string') {
			problems.push(`${where}: text segment without html`);
		}
		if (s.kind === 'fig' && !s.url) problems.push(`${where}: fig without url`);
		if (s.kind === 'table') {
			for (const row of [s.header ?? [], ...(s.rows ?? [])]) {
				if (!Array.isArray(row)) {
					problems.push(`${where}: table row is not an array`);
					continue;
				}
				for (const cell of row) {
					if (!Array.isArray(cell)) {
						problems.push(`${where}: table cell is not an item list`);
						continue;
					}
					for (const it of cell) {
						if (it.kind === 'fig' && !it.url) problems.push(`${where}: table fig without url`);
						if (it.kind === 'text' && typeof it.html !== 'string')
							problems.push(`${where}: table text without html`);
					}
				}
			}
		}
	}
}

const tmp = path.join(root, '.ssr-smoke-tmp');
await fs.promises.mkdir(tmp, { recursive: true });
try {
	let src = await fs.promises.readFile(path.join(root, 'src/lib/components/Segments.svelte'), 'utf8');
	src = src.replace(/^[ \t]*import 'katex\/dist\/katex\.min\.css';$/m, '');
	const out = path.join(tmp, 'Segments.ssr.mjs');
	await fs.promises.writeFile(out, compile(src, { generate: 'server' }).js.code);
	const { render } = await import('svelte/server');
	const { default: Segments } = await import(pathToFileURL(out).href);

	const papers = await get('/api/papers');
	console.log(`papers: ${papers.length}`);
	let nQ = 0;
	let nImg = 0;
	const problems = [];
	for (const p of papers) {
		let qs;
		try {
			qs = await get(`/api/papers/${p.id}/questions`);
		} catch (e) {
			problems.push(`paper ${p.id}: questions failed: ${e.message}`);
			continue;
		}
		for (const q of qs) {
			nQ++;
			const where = `paper ${p.id} q ${q.number}`;
			checkShape(q.question ?? [], where + ' question', problems);
			checkShape(q.solution ?? [], where + ' solution', problems);
			try {
				for (const part of ['question', 'solution']) {
					const { body } = render(Segments, { props: { segments: q[part] ?? [] } });
					nImg += (body.match(/<img/g) || []).length;
					if (!body.includes('pl-math') && (q[part] ?? []).some((s) => s.kind === 'text' && /data-tex/.test(s.html || ''))) {
						problems.push(`${where}: math placeholders lost in render`);
					}
				}
			} catch (e) {
				problems.push(`${where}: render threw: ${e.message}`);
			}
		}
	}
	console.log(`questions: ${nQ}, rendered <img>: ${nImg}`);
	if (problems.length) {
		console.log('FAILURES:');
		for (const f of problems.slice(0, 30)) console.log(' -', f);
		process.exit(1);
	}
	console.log('SMOKE OK');
} finally {
	await fs.promises.rm(tmp, { recursive: true, force: true });
}
