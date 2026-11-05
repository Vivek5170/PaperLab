<script>
	let { label, value } = $props();
</script>

<div class="stat">
	<div class="stat-label">{label}</div>
	<div class="stat-value">{value}</div>
</div>

<style>
	.stat {
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		padding: 18px 20px;
		min-width: 0;
	}
	.stat-label {
		color: var(--pl-ink-soft);
		font-size: 0.85rem;
		margin-bottom: 4px;
	}
	.stat-value {
		font-family: var(--pl-font-display);
		font-size: 2rem;
		line-height: 1.1;
	}
</style>
