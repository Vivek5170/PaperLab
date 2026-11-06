<script>
	/**
	 * Live Answer Sheet: generated key as a document. Pure render of the
	 * shared numbering map + overrides — editing happens in the editor's
	 * KeyTable, values reflect here immediately.
	 */
	let { title = '', numbering, blocks = {}, overrides = {} } = $props();

	const rows = $derived(
		Object.keys(numbering.byNumber ?? {})
			.map(Number)
			.sort((a, b) => a - b)
			.map((n) => {
				const ref = numbering.byNumber[n];
				return {
					n,
					...ref,
					block: blocks[ref.blockId],
					key: `${ref.blockId}:${ref.subIndex}`,
					groupStart: n === 1 || numbering.byNumber[n - 1]?.blockId !== ref.blockId
				};
			})
	);
</script>

<div class="sheet" aria-label="Answer sheet preview">
	<header class="dochead">
		<h2>{title?.trim() || 'Untitled paper'} — Answer key</h2>
		<p class="pl-sub">{numbering.total} answer{numbering.total === 1 ? '' : 's'}</p>
	</header>
	{#if rows.length === 0}
		<p class="pl-sub">Nothing to preview yet.</p>
	{:else}
		<table>
			<thead>
				<tr><th scope="col">Q.No</th><th scope="col">Key</th></tr>
			</thead>
			<tbody>
				{#each rows as r (r.n)}
					{#if r.groupStart && (numbering.byBlock[r.blockId]?.length ?? 1) > 1}
						<tr class="pgroup">
							<td colspan="2">Passage · Paper {r.block?.paperId} · Q{r.block?.number}</td>
						</tr>
					{/if}
					<tr>
						<td class="qn">Q{r.n}</td>
						<td class="key">{overrides[r.key]?.trim() || '—'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.sheet {
		background: #fffdf9;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		box-shadow: var(--pl-shadow-sm);
		padding: 28px 30px;
		max-width: 760px;
	}
	.dochead {
		text-align: center;
		border-bottom: 2px solid var(--pl-ink);
		padding-bottom: 12px;
		margin-bottom: 16px;
	}
	.dochead h2 {
		font-family: var(--pl-font-display);
		font-size: 1.4rem;
		margin: 0 0 2px;
	}
	.dochead .pl-sub {
		margin: 0;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.9rem;
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
		width: 80px;
	}
	.key {
		font-family: var(--pl-font-mono);
	}
	.pgroup td {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
		font-size: 0.8rem;
		font-weight: 600;
	}
</style>
