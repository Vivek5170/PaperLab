<script>
	import { activeCart, carts } from '$lib/carts.js';

	let { item } = $props();

	const inCart = $derived(
		!!$activeCart?.items.some(
			(it) => it.paperId === item.paperId && String(it.number) === String(item.number)
		)
	);

	let note = $state('');

	function toggle() {
		if (inCart) {
			carts.remove(item.paperId, item.number);
			note = 'Removed';
		} else {
			const status = carts.add(item);
			note =
				status === 'ok'
					? `Saved to ${$activeCart?.name ?? 'cart'}`
					: status === 'duplicate'
						? 'Already in cart'
						: 'Could not add';
		}
		setTimeout(() => (note = ''), 1600);
	}
</script>

<button
	type="button"
	class="addbtn"
	class:in={inCart}
	onclick={toggle}
	title={inCart ? 'Remove from cart' : `Add to ${$activeCart?.name ?? 'cart'}`}
	aria-pressed={inCart}
	aria-label={inCart
		? `Remove question ${item.number} from cart`
		: `Add question ${item.number} to cart`}
>
	{#if inCart}✓ In cart{:else}+ Cart{/if}
</button>
{#if note}<span class="pl-sub note" role="status">{note}</span>{/if}

<style>
	.addbtn {
		border: 1px solid var(--pl-line);
		background: var(--pl-surface);
		border-radius: var(--pl-radius-pill);
		padding: 6px 12px;
		min-height: 32px;
		font-size: 0.78rem;
		font-weight: 600;
		cursor: pointer;
		white-space: nowrap;
	}
	.addbtn:hover {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.addbtn.in {
		background: var(--pl-pine-soft);
		border-color: var(--pl-pine);
		color: var(--pl-pine);
	}
	.note {
		margin-left: 8px;
		font-size: 0.75rem;
	}
</style>
