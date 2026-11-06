<script>
	import { toRoman } from '$lib/numbering.js';
	import { isParagraphId } from '$lib/paragraph.js';
	import { sectionMeta } from '$lib/sectionMeta.js';
	import QuestionSheetBlock from '$lib/components/QuestionSheetBlock.svelte';

	/**
	 * Live Question Sheet: the actual paper output — section headings,
	 * inline generated numbers, passages headed Paragraph I/II with
	 * per-question sub-numbers, real segments, figures via existing URLs.
	 * Pure function of (ordered, numbering, draft title/mode). */

	let { title = '', ordered = [], numbering, sections = [], mode = 'paper' } = $props();

	// Paragraph I, II... in document order (JEE convention, no numbers).
	const paraIndex = $derived.by(() => {
		const m = new Map();
		let i = 0;
		for (const e of ordered) if (isParagraphId(e.number, e.qtype)) m.set(e.blockId, toRoman(++i));
		return m;
	});

	const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
</script>

<div class="sheet" aria-label="Question sheet preview">
	<header class="dochead">
		<h2>{title?.trim() || 'Untitled paper'}</h2>
		<p class="pl-sub">{mode === 'paper' ? 'Question paper' : 'Assignment'} · {numbering.total} question{numbering.total === 1 ? '' : 's'}</p>
	</header>
	{#if ordered.length === 0}
		<p class="pl-sub">Nothing to preview yet — import a cart in the editor.</p>
	{:else if mode === 'assignment'}
		{#each ordered as entry (entry.blockId)}
			<QuestionSheetBlock block={entry} numbers={numbering.byBlock[entry.blockId] ?? []} paraLabel={paraIndex.get(entry.blockId) ?? null} />
		{/each}
	{:else}
				{#each sections as s, si (s.id)}
					{@const secNums = (s.blockIds ?? []).flatMap((bid) => numbering.byBlock[bid] ?? [])}
					{#if secNums.length > 0}
						{@const meta = sectionMeta(s.atype, secNums.length, (s.blockIds ?? []).length)}
						<div class="sechead">
							<h3>SECTION–{(LETTERS[si] ?? `X${si + 1}`)}</h3>
							<p class="seckind">({meta.kind})</p>
							<ul>
								{#each meta.lines as line (line)}
									<li>{line}</li>
								{/each}
							</ul>
						</div>
				{#each s.blockIds as bid (bid)}
					{@const entry = ordered.find((o) => o.blockId === bid)}
					{#if entry}
						<QuestionSheetBlock block={entry} numbers={numbering.byBlock[bid] ?? []} paraLabel={paraIndex.get(bid) ?? null} />
					{/if}
				{/each}
			{/if}
		{/each}
	{/if}
</div>

<style>
	.sheet {
		font-size: 0.8125rem;
		line-height: 1.6;
		background: #ffffff;
		color: #111111;
		border: 1px solid var(--pl-line);
		border-radius: 2px;
		box-shadow: var(--pl-shadow-md);
		padding: 44px 52px;
		width: 100%;
		max-width: 794px;
		margin: 0 auto;
	}
	.dochead {
		text-align: center;
		border-bottom: 2px solid var(--pl-ink);
		padding-bottom: 12px;
		margin-bottom: 20px;
	}
	.dochead h2 {
		font-family: var(--pl-font-display);
		font-size: 1.3rem;
		margin: 0 0 2px;
	}
	.dochead .pl-sub {
		margin: 0;
	}
	.sheet :global(.fig) {
		margin: 12px 0 14px;
	}
	.sheet :global(.fig img) {
		max-width: 250px;
	}
	.sheet :global(.pl-table img) {
		max-width: 200px;
	}
	.sechead {
		margin: 20px 0 12px;
		padding-bottom: 8px;
		border-bottom: 1px solid var(--pl-line);
	}
	.sechead:first-of-type {
		margin-top: 0;
	}
	.sechead h3 {
		font-family: var(--pl-font-display);
		font-size: 1rem;
		text-align: center;
		margin: 0 0 2px;
		letter-spacing: 0.04em;
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
