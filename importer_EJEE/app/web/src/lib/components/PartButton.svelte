<script>
	/**
	 * Cart control for the 15-question PART an item belongs to. A question
	 * cannot be converted alone: PaperLab receives "<Book> — Part N".
	 */
	import { api } from '$lib/api.js';
	import { refreshStatus, toast } from '$lib/stores.js';
	import { statusLabel } from '$lib/labels.js';

	let { item, size = 'sm', onchange = () => {} } = $props();
	let busy = $state(false);

	async function add(e) {
		e.preventDefault();
		e.stopPropagation();
		busy = true;
		try {
			await api.addPart(item.slug, item.part);
			toast(`Added ${item.source} — Part ${item.part} to the cart.`, 'ok');
			onchange('in_cart');
			refreshStatus();
		} catch (err) {
			toast(err.message, 'warn', 8000);
		} finally {
			busy = false;
		}
	}

	async function remove(e) {
		e.preventDefault();
		e.stopPropagation();
		busy = true;
		try {
			await api.removePart(item.slug, item.part);
			onchange('not_started');
			refreshStatus();
		} catch (err) {
			toast(err.message, 'warn');
		} finally {
			busy = false;
		}
	}
</script>

{#if item.status === 'in_cart'}
	<button type="button" class="pb on" class:lg={size === 'lg'} disabled={busy} onclick={remove}
		aria-label={`Remove part ${item.part} from the cart`} title="Remove this part from the cart">
		✓ Part {item.part} in cart
	</button>
{:else if item.status && item.status !== 'not_started'}
	<a class="state" class:lg={size === 'lg'} class:warn={item.status === 'failed'}
		class:good={item.status === 'published'} href="/process" onclick={(e) => e.stopPropagation()}>
		Part {item.part} · {statusLabel(item.status)}
	</a>
{:else}
	<button type="button" class="pb" class:lg={size === 'lg'} disabled={busy} onclick={add}
		aria-label={`Add part ${item.part} (up to 15 questions) to the cart`} title="Adds the whole 15-question part">
		+ Part {item.part}
	</button>
{/if}

<style>
	.pb,
	.state {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		border-radius: var(--pl-radius-pill);
		border: 1px solid var(--pl-line);
		background: var(--pl-surface);
		color: var(--pl-ink);
		font-weight: 600;
		font-size: 0.75rem;
		padding: 4px 10px;
		min-height: 30px;
		white-space: nowrap;
		text-decoration: none;
	}
	.pb:hover:not(:disabled) {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.pb.on {
		background: var(--pl-pine-soft);
		border-color: var(--pl-pine);
		color: var(--pl-pine);
	}
	.state.warn {
		background: var(--pl-ochre-soft);
		border-color: var(--pl-ochre);
		color: var(--pl-ochre);
	}
	.state.good {
		background: var(--pl-pine-soft);
		border-color: var(--pl-pine);
		color: var(--pl-pine);
	}
	.lg {
		font-size: 0.85rem;
		padding: 8px 16px;
		min-height: 40px;
	}
</style>
