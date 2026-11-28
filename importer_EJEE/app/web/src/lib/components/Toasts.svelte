<script>
	import { toasts } from '$lib/stores.js';
</script>

<div class="toasts" aria-live="polite">
	{#each $toasts as t (t.id)}
		<div class="toast" class:ok={t.tone === 'ok'} class:warn={t.tone === 'warn'} role="status">{t.text}</div>
	{/each}
</div>

<style>
	.toasts {
		position: fixed;
		right: 20px;
		bottom: 20px;
		z-index: 80;
		display: flex;
		flex-direction: column;
		gap: 8px;
		max-width: min(440px, calc(100vw - 40px));
	}
	.toast {
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-left: 4px solid var(--pl-ink-soft);
		border-radius: var(--pl-radius-sm);
		box-shadow: var(--pl-shadow-md);
		padding: 12px 14px;
		font-size: 0.85rem;
	}
	.toast.ok {
		border-left-color: var(--pl-pine);
	}
	.toast.warn {
		border-left-color: var(--pl-ochre);
	}
</style>
