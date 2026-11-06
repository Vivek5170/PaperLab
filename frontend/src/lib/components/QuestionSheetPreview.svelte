<script>
	/**
	 * Live Question Sheet on real A4 pages: section headings, inline
	 * generated numbers, passages headed Paragraph I/II. Pure function
	 * of (ordered, numbering, draft title/mode) — no numbering of its own.
	 */
	import { toRoman } from '$lib/numbering.js';
	import { isParagraphId } from '$lib/paragraph.js';
	import { sectionMeta } from '$lib/sectionMeta.js';
	import QuestionSheetBlock from '$lib/components/QuestionSheetBlock.svelte';
	import PagedSheet from '$lib/components/PagedSheet.svelte';

	let { title = '', ordered = [], numbering, sections = [], mode = 'paper' } = $props();

	const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

	// Paragraph I, II... in document order (no numbers in the header).
	const paraIndex = $derived.by(() => {
		const m = new Map();
		let i = 0;
		for (const e of ordered) if (isParagraphId(e.number, e.qtype)) m.set(e.blockId, toRoman(++i));
		return m;
	});

	const rows = $derived.by(() => {
		const out = [{ id: 'doc', kind: 'doc', header: true }];
		if (mode === 'assignment') {
			for (const e of ordered) out.push({ id: e.blockId, kind: 'q' });
			return out;
		}
		for (const s of sections) {
			const bids = (s.blockIds ?? []).filter((bid) => (numbering.byBlock[bid] ?? []).length > 0);
			if (!bids.length) continue;
			out.push({ id: `sec:${s.id}`, kind: 'sec', header: true, si: sections.indexOf(s) });
			for (const bid of bids) out.push({ id: bid, kind: 'q' });
		}
		return out;
	});
</script>

<PagedSheet {rows} row={qrow} />
{#snippet qrow(def)}
	{#if def.kind === 'doc'}
		<header class="dochead">
			<h2>{title?.trim() || 'Untitled paper'}</h2>
			<p class="pl-sub">{mode === 'paper' ? 'Question paper' : 'Assignment'} · {numbering.total} questions</p>
		</header>
	{:else if def.kind === 'sec'}
		{@const s = sections[def.si]}
		{@const secNums = (s.blockIds ?? []).flatMap((bid) => numbering.byBlock[bid] ?? [])}
		{@const meta = sectionMeta(s.atype, secNums.length, (s.blockIds ?? []).length)}
		<div class="sechead">
			<h3>SECTION–{(LETTERS[def.si] ?? `X${def.si + 1}`)}</h3>
			<p class="seckind">({meta.kind})</p>
			<ul>
				{#each meta.lines as line (line)}
					<li>{line}</li>
				{/each}
			</ul>
		</div>
	{:else}
		{@const entry = ordered.find((o) => o.blockId === def.id)}
		{#if entry}
			<QuestionSheetBlock
				block={entry}
				numbers={numbering.byBlock[def.id] ?? []}
				paraLabel={paraIndex.get(def.id) ?? null}
			/>
		{/if}
	{/if}
{/snippet}

<style>
	.dochead {
		text-align: center;
		border-bottom: 2px solid #111;
		padding-bottom: 10px;
		margin-bottom: 14px;
	}
	.dochead h2 {
		font-family: var(--pl-font-display);
		font-size: 1.3rem;
		margin: 0 0 2px;
		color: #111;
	}
	.dochead .pl-sub {
		margin: 0;
	}
	.sechead {
		margin: 4px 0 10px;
		padding-bottom: 8px;
		border-bottom: 1px solid #111;
	}
	.sechead h3 {
		font-family: var(--pl-font-display);
		font-size: 1rem;
		text-align: center;
		margin: 0 0 2px;
		letter-spacing: 0.04em;
		color: #111;
	}
	.seckind {
		text-align: center;
		font-weight: 700;
		font-size: 0.82rem;
		margin: 0 0 8px;
	}
	.sechead ul {
		margin: 0;
		padding-left: 18px;
		font-size: 0.78rem;
		line-height: 1.55;
	}
</style>
