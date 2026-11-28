<script>
	import { appStatus } from '$lib/stores.js';

	let { action = 'process or publish' } = $props();
	const missing = $derived($appStatus?.missing ?? []);
</script>

{#if missing.length}
	<div class="pl-error notice" role="status">
		<strong>Finish setup before you {action}.</strong>
		<p>Missing: {missing.map((m) => m.label).join(', ')}.</p>
		<a class="pl-btn" href="/settings">Open Settings</a>
	</div>
{/if}

<style>
	.notice {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px 16px;
		margin: 12px 0;
	}
	.notice p {
		margin: 0;
		flex: 1;
		min-width: 200px;
	}
</style>
