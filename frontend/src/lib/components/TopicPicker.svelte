<script>
	/** Searchable topic picker: checkbox list with code/name search. */
	let { options = [], value = $bindable([]) } = $props();

	let q = $state('');

	const shown = $derived(
		(!q.trim()
			? options
			: options.filter((o) =>
					`${o.code} ${o.path}`.toLowerCase().includes(q.trim().toLowerCase())
				)
		).slice(0, 80)
	);

	const selectedPaths = $derived(
		value.map((c) => options.find((o) => o.code === c)).filter(Boolean)
	);

	function toggle(code) {
		value = value.includes(code) ? value.filter((c) => c !== code) : [...value, code];
	}
</script>

<div class="picker">
	{#if value.length > 0}
		<div class="chips" aria-label="Selected topics">
			{#each selectedPaths as s, si (si)}
				<span class="pl-chip">
					{s.code}
					<button
						type="button"
						aria-label={`Remove ${s.code}`}
						onclick={() => toggle(s.code)}
					>
						×
					</button>
				</span>
			{/each}
		</div>
	{/if}
	<input
		type="search"
		bind:value={q}
		placeholder="Search topics by code or name…"
		aria-label="Search topics"
	/>
	<div class="list" role="group" aria-label="Topic options">
		{#if shown.length === 0}
			<p class="pl-sub">No matches. The first topic picked becomes the primary.</p>
		{/if}
		{#each shown as opt (opt.code)}
			<label class="row">
				<input
					type="checkbox"
					checked={value.includes(opt.code)}
					onchange={() => toggle(opt.code)}
				/>
				<span><strong class="pl-mono">{opt.code}</strong> - {opt.path}</span>
			</label>
		{/each}
	</div>
	<p class="pl-sub">{value.length} selected. First topic is the primary.</p>
</div>

<style>
	.picker {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.chips .pl-chip button {
		border: none;
		background: none;
		cursor: pointer;
		font-size: 1rem;
		line-height: 1;
		min-height: 0;
		padding: 0 0 0 4px;
	}
	.list {
		max-height: 220px;
		overflow-y: auto;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-surface);
	}
	.row {
		display: flex !important;
		flex-direction: row !important;
		align-items: flex-start;
		gap: 10px;
		padding: 8px 10px;
		cursor: pointer;
		font-weight: 500 !important;
		margin: 0;
		border-left: 3px solid transparent;
	}
	.row:hover {
		background: var(--pl-raised);
	}
	.row input {
		accent-color: var(--pl-seal);
		min-height: 0;
		margin-top: 2px;
	}
</style>
