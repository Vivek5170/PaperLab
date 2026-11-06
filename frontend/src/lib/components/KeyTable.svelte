<script>
	/**
	 * Answer key: one row per GENERATED number from the shared numbering
	 * map. Overrides are keyed `blockId:subIndex` and follow the question
	 * through renumbering. Paragraph sub-rows group under one header.
	 */
	let { numbering, blocks = {}, overrides = {}, parsed = {}, onOverride } = $props();

	const rows = $derived(
		Object.keys(numbering.byNumber ?? {})
			.map(Number)
			.sort((a, b) => a - b)
			.map((n) => {
				const ref = numbering.byNumber[n];
				const block = blocks[ref.blockId];
				return {
					n,
					...ref,
					block,
					key: `${ref.blockId}:${ref.subIndex}`,
					groupStart: n === 1 || numbering.byNumber[n - 1]?.blockId !== ref.blockId
				};
			})
	);
</script>

<div class="key">
	<h3>Answer key</h3>
	{#if rows.length === 0}
		<p class="pl-sub">No questions yet — import a cart to start the key.</p>
	{:else}
		<table>
			<thead>
				<tr><th scope="col">Q.No</th><th scope="col">Key</th></tr>
			</thead>
			<tbody>
				{#each rows as r (r.n)}
					{#if r.groupStart && (numbering.byBlock[r.blockId]?.length ?? 1) > 1}
						<tr class="pgroup">
							<td colspan="2">Passage · {numbering.byBlock[r.blockId].length} questions</td>
						</tr>
					{/if}
					<tr>
						<td class="qn">Q{r.n}</td>
						<td>
							<input
								type="text"
								value={overrides[r.key] ?? parsed[r.blockId]?.[r.subIndex] ?? ''}
								placeholder="—"
								maxlength="200"
								aria-label={`Answer key for generated question ${r.n}`}
								oninput={(e) => onOverride?.(r.blockId, r.subIndex, e.currentTarget.value)}
							/>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.key h3 {
		margin: 0 0 2px;
		font-size: 1.1rem;
	}
	.key .pl-sub {
		margin: 0 0 10px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}
	th, td {
		text-align: left;
		padding: 6px 10px;
		border-bottom: 1px solid var(--pl-line);
	}
	th {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--pl-ink-soft);
	}
	.qn {
		font-weight: 700;
		white-space: nowrap;
		width: 64px;
	}
	.src {
		color: var(--pl-ink-soft);
		font-size: 0.78rem;
	}
	.pgroup td {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
		font-size: 0.78rem;
		font-weight: 600;
	}
	td input {
		width: 100%;
		min-height: 32px;
		font-size: 0.85rem;
	}
</style>
