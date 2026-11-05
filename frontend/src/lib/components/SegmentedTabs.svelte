<script>
	/** Segmented pill tabs with arrow-key support (ARIA tabs pattern). */
	let { tabs = [], value = $bindable(tabs[0]?.id) } = $props();

	let buttons = $state([]);

	function focusTab(i) {
		const n = tabs.length;
		const next = ((i % n) + n) % n;
		buttons[next]?.focus();
		value = tabs[next].id;
	}

	function onKeydown(event, i) {
		if (event.key === 'ArrowRight') {
			event.preventDefault();
			focusTab(i + 1);
		} else if (event.key === 'ArrowLeft') {
			event.preventDefault();
			focusTab(i - 1);
		} else if (event.key === 'Home') {
			event.preventDefault();
			focusTab(0);
		} else if (event.key === 'End') {
			event.preventDefault();
			focusTab(tabs.length - 1);
		}
	}
</script>

<div class="seg" role="tablist" aria-label="View">
	{#each tabs as tab, i (tab.id)}
		<button
			type="button"
			role="tab"
			aria-selected={value === tab.id}
			tabindex={value === tab.id ? 0 : -1}
			class="seg-btn"
			class:active={value === tab.id}
			bind:this={buttons[i]}
			onclick={() => (value = tab.id)}
			onkeydown={(e) => onKeydown(e, i)}
		>
			{tab.label}
		</button>
	{/each}
</div>

<style>
	.seg {
		display: inline-flex;
		gap: 4px;
		background: var(--pl-raised);
		border-radius: var(--pl-radius-md);
		padding: 4px;
	}
	.seg-btn {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		border: none;
		background: none;
		border-radius: 10px;
		padding: 10px 20px;
		color: var(--pl-ink-soft);
		font-weight: 500;
		min-height: 44px;
	}
	.seg-btn.active {
		background: var(--pl-surface);
		color: var(--pl-ink);
		font-weight: 600;
		box-shadow: var(--pl-shadow-sm);
	}
</style>
