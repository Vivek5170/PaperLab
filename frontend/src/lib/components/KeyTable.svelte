<script>
	/**
	 * Answer key as a compact bordered grid: COLS (Q.No, Key) pairs per
	 * visual row, so a 30-question key fits a fraction of a page instead
	 * of two. One row per GENERATED number from the shared numbering map.
	 * Overrides are keyed `blockId:subIndex` and follow the question
	 * through renumbering.
	 */
	let { numbering, blocks = {}, overrides = {}, parsed = {}, onOverride } = $props();

	const COLS = 5;

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
					key: `${ref.blockId}:${ref.subIndex}`
				};
			})
	);

	const grid = $derived.by(() => {
		const out = [];
		for (let i = 0; i < rows.length; i += COLS) out.push(rows.slice(i, i + COLS));
		return out;
	});
</script>

<div class="key">
	<h3>Answer key</h3>
	{#if rows.length === 0}
		<p class="pl-sub">No questions yet — import a cart to start the key.</p>
	{:else}
		<table>
			<thead>
				<tr>
					{#each Array(COLS) as _, c (c)}
						<th scope="col">Q.No</th><th scope="col">Key</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each grid as line, li (li)}
					<tr>
						{#each line as r (r.n)}
							<td class="qn">Q{r.n}</td>
							<td class="kv">
								<input
									type="text"
									value={overrides[r.key] ?? parsed[r.blockId]?.[r.subIndex] ?? ''}
									placeholder="—"
									maxlength="200"
									aria-label={`Answer key for generated question ${r.n}`}
									oninput={(e) => onOverride?.(r.blockId, r.subIndex, e.currentTarget.value)}
								/>
							</td>
						{/each}
						{#if line.length < COLS}
							{#each Array(COLS - line.length) as _, c (`e${c}`)}
								<td class="qn empty"></td><td class="kv empty"></td>
							{/each}
						{/if}
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.key h3 {
		margin: 0 0 4px;
		font-size: 1.1rem;
	}
	.key .pl-sub {
		margin: 0 0 10px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.8rem;
		/* Paper-locked colors: the sheet is always light paper for print
		   fidelity, so never use theme vars here (dark mode unreadable). */
		color: #1c1e21;
	}
	th, td {
		border: 1px solid #d9d1bf;
		padding: 3px 6px;
	}
	th {
		font-size: 0.68rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #5c6066;
		background: #f1ece1;
	}
	.qn {
		font-weight: 700;
		white-space: nowrap;
		text-align: center;
		background: #f1ece1;
		color: #1c1e21;
		width: 40px;
	}
	td.empty {
		background: none;
	}
	td input {
		width: 100%;
		min-width: 64px;
		min-height: 28px;
		border: none;
		background: transparent;
		text-align: center;
		font-weight: 700;
		font-size: 0.8rem;
		color: inherit;
		padding: 1px 2px;
	}
	td input:focus {
		outline: 2px solid var(--pl-seal);
		outline-offset: -2px;
		background: #fff;
	}
</style>
