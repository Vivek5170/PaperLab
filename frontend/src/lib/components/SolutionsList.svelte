<script>
	/**
	 * Full solutions: one section per block in document order, each headed
	 * by its generated numbers from the shared numbering map. Paragraph
	 * context renders once; per-subquestion anchors carry the numbers.
	 */
	import SolutionBlock from '$lib/components/SolutionBlock.svelte';

	let { ordered = [], numbering } = $props();
</script>

<div class="sols">
	<h3>Solutions</h3>
	<p class="pl-sub">Follows the key. Each solution is headed by the same generated numbers as its question.</p>
	{#if ordered.length === 0}
		<p class="pl-sub">No solutions yet.</p>
	{:else}
		{#each ordered as entry (entry.blockId)}
			{@const nums = numbering.byBlock[entry.blockId] ?? []}
			<SolutionBlock block={entry} numbers={nums} />
			{#if nums.length > 1}
				<ul class="anchors" aria-label={`Sub-solutions for ${nums.map((n) => `Q${n}`).join(', ')}`}>
					{#each nums as n (n)}
						<li><span class="anch">Q{n}</span> <span class="pl-sub">solved in the passage solution above</span></li>
					{/each}
				</ul>
			{/if}
		{/each}
	{/if}
</div>

<style>
	.sols h3 {
		margin: 0 0 2px;
		font-size: 1.1rem;
	}
	.sols > .pl-sub {
		margin: 0 0 6px;
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
	.anchors .pl-sub {
		font-size: 0.78rem;
	}
</style>
