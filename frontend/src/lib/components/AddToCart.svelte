<script>
	import { activeCart, carts } from '$lib/carts.js';

	let { item, variant = 'chip' } = $props();

	const inCart = $derived(
		!!$activeCart?.items.some(
			(it) => it.paperId === item.paperId && String(it.number) === String(item.number)
		)
	);

	function toggle() {
		if (inCart) carts.remove(item.paperId, item.number);
		else carts.add(item);
	}
</script>

<button
	type="button"
	class="cartbtn {variant}"
	class:in={inCart}
	onclick={toggle}
	title={inCart
		? `Remove question ${item.number} from ${$activeCart?.name ?? 'cart'}`
		: `Add question ${item.number} to ${$activeCart?.name ?? 'cart'}`}
	aria-pressed={inCart}
	aria-label={inCart
		? `Remove question ${item.number} from cart`
		: `Add question ${item.number} to cart`}
>
	<svg viewBox="0 0 902.86 902.86" fill="currentColor" aria-hidden="true"><path d="m671.504 577.829 110.485-432.609h120.871v-68h-173.686l-26.046 101.98-703.128-.503 74.753 399.129h596.751zm14.262-330.641-67.077 262.64h-487.49l-49.271-263.072z"/><path d="m578.418 825.641c59.961 0 108.743-48.783 108.743-108.744s-48.782-108.742-108.743-108.742h-409.701c-59.961 0-108.744 48.781-108.744 108.742s48.782 108.744 108.744 108.744 108.743-48.783 108.743-108.744c0-14.4-2.821-28.152-7.927-40.742h208.069c-5.107 12.59-7.928 26.342-7.928 40.742.001 59.961 48.783 108.744 108.744 108.744zm-368.958-108.744c0 22.467-18.277 40.744-40.743 40.744s-40.744-18.277-40.744-40.744c0-22.465 18.277-40.742 40.744-40.742 22.466-0 40.743 18.277 40.743 40.742zm409.702 0c0 22.467-18.277 40.744-40.743 40.744s-40.743-18.277-40.743-40.744c0-22.465 18.277-40.742 40.743-40.742s40.743 18.277 40.743 40.742z"/></svg>
</button>

<style>
	.cartbtn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--pl-line);
		background: var(--pl-surface);
		color: var(--pl-ink-soft);
		cursor: pointer;
		flex-shrink: 0;
		padding: 0;
		min-height: 0;
		min-width: 0;
		box-sizing: border-box;
	}
	.cartbtn:hover {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.cartbtn.in {
		background: var(--pl-pine-soft);
		border-color: var(--pl-pine);
		color: var(--pl-pine);
	}
	/* Search-card chips row: same height as the type chip (~22px). */
	.cartbtn.chip {
		width: 28px;
		height: 22px;
		border-radius: 6px;
	}
	.cartbtn.chip svg {
		width: 14px;
		height: 14px;
	}
	/* Reader title row: match the editlink tool button. */
	.cartbtn.tool {
		width: 34px;
		height: 34px;
		border-radius: var(--pl-radius-sm);
	}
	.cartbtn.tool svg {
		width: 16px;
		height: 16px;
	}
</style>
