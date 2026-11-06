<script>
	/**
	 * Compact multi-select dropdown: button shows label + selected count,
	 * panel lists options with counts and checkmarks, footer clears the group.
	 * Union within the group; the page intersects across groups.
	 */
	let { label, options = [], selected = $bindable([]), format = (v) => v } = $props();

	let open = $state(false);
	let panel = $state(null);

	const count = $derived(selected.length);

	function toggle(value) {
		selected = selected.includes(value)
			? selected.filter((v) => v !== value)
			: [...selected, value];
	}

	function close() {
		open = false;
	}
</script>

<svelte:window
	onclick={(e) => {
		if (open && panel && !panel.contains(e.target)) close();
	}}
	onkeydown={(e) => {
		if (e.key === 'Escape') close();
	}}
/>

<div class="dd" bind:this={panel}>
	<button
		type="button"
		class="dd-btn"
		class:active={count > 0}
		aria-expanded={open}
		aria-haspopup="listbox"
		onclick={() => (open = !open)}
	>
		<span class="dd-label">{label}{count > 0 ? ` · ${count}` : ''}</span>
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
	</button>
	{#if open}
		<div class="dd-panel" role="listbox" aria-label={label} aria-multiselectable="true">
			{#if options.length === 0}
				<p class="dd-empty">No values tagged yet.</p>
			{:else}
				<ul>
					{#each options as opt (opt.value)}
						<li>
							<button
								type="button"
								role="option"
								aria-selected={selected.includes(opt.value)}
								class="dd-opt"
								class:on={selected.includes(opt.value)}
								onclick={() => toggle(opt.value)}
							>
								<span class="tick" aria-hidden="true">
									{#if selected.includes(opt.value)}✓{/if}
								</span>
								<span class="opt-label">{format(opt.value)}</span>
								{#if opt.count != null}
									<span class="opt-count pl-mono">{opt.count}</span>
								{/if}
							</button>
						</li>
					{/each}
				</ul>
			{/if}
			<div class="dd-foot">
				<button type="button" class="dd-clear" disabled={count === 0} onclick={() => (selected = [])}>
					Clear
				</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.dd {
		position: relative;
	}
	.dd-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		background: var(--pl-surface);
		color: var(--pl-ink-soft);
		font-weight: 600;
		font-size: 0.82rem;
		padding: 8px 14px;
		min-height: 40px;
		white-space: nowrap;
	}
	.dd-btn:hover {
		background: var(--pl-raised);
		color: var(--pl-ink);
	}
	.dd-btn.active {
		background: var(--pl-seal-soft);
		border-color: var(--pl-seal);
		color: var(--pl-ink);
	}
	.dd-btn svg {
		width: 14px;
		height: 14px;
		flex-shrink: 0;
	}
	.dd-panel {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 50;
		min-width: 240px;
		max-width: min(320px, 88vw);
		max-height: 320px;
		display: flex;
		flex-direction: column;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		box-shadow: var(--pl-shadow-md);
	}
	.dd-panel ul {
		list-style: none;
		margin: 0;
		padding: 6px;
		overflow-y: auto;
		min-height: 0;
	}
	.dd-opt {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		border: none;
		background: none;
		padding: 9px 10px;
		border-radius: var(--pl-radius-sm);
		font-size: 0.85rem;
		text-align: left;
		min-height: 44px;
	}
	.dd-opt:hover {
		background: var(--pl-raised);
	}
	.tick {
		width: 20px;
		height: 20px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		font-size: 0.8rem;
		color: #fff;
	}
	.dd-opt.on .tick {
		background: var(--pl-seal);
		border-color: var(--pl-seal);
	}
	.opt-label {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.opt-count {
		color: var(--pl-ink-soft);
		font-size: 0.75rem;
	}
	.dd-empty {
		margin: 0;
		padding: 14px;
		color: var(--pl-ink-soft);
		font-size: 0.85rem;
	}
	.dd-foot {
		border-top: 1px solid var(--pl-line);
		padding: 6px;
	}
	.dd-clear {
		border: none;
		background: none;
		color: var(--pl-seal);
		font-weight: 600;
		font-size: 0.82rem;
		padding: 8px 10px;
		min-height: 44px;
	}
	.dd-clear:disabled {
		color: var(--pl-ink-soft);
		opacity: 0.5;
		cursor: default;
	}
</style>
