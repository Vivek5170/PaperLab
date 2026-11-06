<script>
	/**
	 * Live Question Sheet: the actual paper output — section headings,
	 * continuous generated numbers, real segments (passages rendered once
	 * with their range heading), figures via existing URLs. Pure function
	 * of (ordered, numbering, draft title/mode): no numbering of its own.
	 */
	import QuestionSheetBlock from '$lib/components/QuestionSheetBlock.svelte';

	let { title = '', ordered = [], numbering, sections = [], mode = 'paper' } = $props();
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
			<QuestionSheetBlock block={entry} numbers={numbering.byBlock[entry.blockId] ?? []} />
		{/each}
	{:else}
		{#each sections as s (s.id)}
			{#if (s.blockIds ?? []).length > 0}
				<h3 class="sechead">
					{s.title}
					{#if s.atype === 'passage'}
						<span class="tag">Passages — kept whole, numbered per question</span>
					{:else}
						<span class="tag">{s.atype.toUpperCase()}</span>
					{/if}
				</h3>
				{#each s.blockIds as bid (bid)}
					{@const entry = ordered.find((o) => o.blockId === bid)}
					{#if entry}
						<QuestionSheetBlock block={entry} numbers={numbering.byBlock[bid] ?? []} />
					{/if}
				{/each}
			{/if}
		{/each}
	{/if}
</div>

<style>
	.sheet {
		background: #fffdf9;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		box-shadow: var(--pl-shadow-sm);
		padding: 28px 30px;
		width: 100%;
		max-width: 800px;
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
		font-size: 1.5rem;
		margin: 0 0 2px;
	}
	.dochead .pl-sub {
		margin: 0;
	}
	.sechead {
		font-family: var(--pl-font-display);
		font-size: 1.15rem;
		margin: 22px 0 12px;
		padding-bottom: 6px;
		border-bottom: 1px solid var(--pl-line);
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 10px;
	}
	.sechead:first-of-type {
		margin-top: 0;
	}
	.tag {
		font-family: var(--pl-font-ui);
		font-size: 0.72rem;
		font-weight: 700;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		padding: 2px 8px;
		color: var(--pl-ink-soft);
	}
</style>
