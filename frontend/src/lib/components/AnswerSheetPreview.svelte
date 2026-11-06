<script>
	/**
	 * Live Answer Sheet on real A4 pages: page(s) of key first (Q.No +
	 * Key, auto-filled from filed answers, manual overrides win), then
	 * detailed solutions on fresh pages. Same generated numbers as the
	 * Question Sheet. Pure render of the shared numbering map.
	 */
	import KeyTable from '$lib/components/KeyTable.svelte';
	import SolutionBlock from '$lib/components/SolutionBlock.svelte';
	import PagedSheet from '$lib/components/PagedSheet.svelte';

	let { title = '', numbering, blocks = {}, overrides = {}, parsed = {}, ordered = [], onOverride } = $props();

	const rows = $derived.by(() => {
		const out = [
			{ id: 'doc', kind: 'doc', header: true },
			{ id: 'key', kind: 'key', header: true }
		];
		if (ordered.length > 0) out.push({ id: 'solshead', kind: 'solshead', header: true, breakBefore: true });
		for (const e of ordered) out.push({ id: e.blockId, kind: 'sol' });
		return out;
	});
</script>

<PagedSheet {rows} row={arow} />
{#snippet arow(def)}
	{#if def.kind === 'doc'}
		<header class="dochead">
			<h2>{title?.trim() || 'Untitled paper'} — Answer key</h2>
		</header>
	{:else if def.kind === 'key'}
		<KeyTable {numbering} {blocks} {overrides} {parsed} {onOverride} />
	{:else if def.kind === 'solshead'}
		<h3 class="solshead">Detailed solutions</h3>
	{:else}
		{@const entry = ordered.find((o) => o.blockId === def.id)}
		{#if entry}
			<SolutionBlock block={entry} numbers={numbering.byBlock[def.id] ?? []} />
			{@const nums = numbering.byBlock[def.id] ?? []}
			{#if nums.length > 1}
				<ul class="anchors" aria-label={`Sub-solutions for ${nums.map((n) => `Q${n}`).join(', ')}`}>
					{#each nums as n (n)}
						<li><span class="anch">Q{n}</span></li>
					{/each}
				</ul>
			{/if}
		{/if}
	{/if}
{/snippet}

<style>
	.dochead {
		text-align: center;
		border-bottom: 2px solid #111;
		padding-bottom: 10px;
		margin-bottom: 12px;
	}
	.dochead h2 {
		font-family: var(--pl-font-display);
		font-size: 1.25rem;
		margin: 0;
		color: #111;
	}
	.solshead {
		font-family: var(--pl-font-display);
		font-size: 1.15rem;
		margin: 0 0 8px;
		color: #111;
	}
	.anchors {
		list-style: none;
		margin: 4px 0 8px;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.anch {
		font-weight: 700;
		font-size: 0.8rem;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		padding: 1px 8px;
	}
	.solshead + :global(*) {
		margin-top: 0;
	}
</style>
