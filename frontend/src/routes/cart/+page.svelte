<script>
	import { cartStore, activeCart, carts, cartCorrupt } from '$lib/carts.js';
	import CartCard from '$lib/components/CartCard.svelte';

	let newName = $state('');
	let renameValue = $state('');
	let confirmClear = $state(false);
	let deleteId = $state(null);

	const cart = $derived($activeCart);

	$effect(() => {
		renameValue = cart?.name ?? '';
	});

	function create() {
		carts.create(newName.trim() || undefined);
		newName = '';
	}
</script>

<svelte:head><title>Cart - PaperLab</title></svelte:head>

<h1>Question cart</h1>
<p class="pl-sub">
	Pick questions from Search or the reader. Carts live only in this browser —
	no server changes, no uploads. Paragraph groups always move as one block.
</p>

{#if $cartCorrupt}
	<div class="pl-error" role="alert">
		<strong>Saved cart data was corrupt.</strong>
		<p class="pl-mono">Started fresh; the broken copy was backed up in this browser.</p>
		<button type="button" class="pl-btn" onclick={() => cartCorrupt.set(false)}>Dismiss</button>
	</div>
{/if}

<div class="bar">
	<label class="pick">
		<span class="pl-sub">Active cart</span>
		<select
			value={$cartStore.activeId}
			onchange={(e) => carts.switch(e.currentTarget.value)}
			aria-label="Active cart"
		>
			{#each $cartStore.carts as c (c.id)}
				<option value={c.id}>{c.name} · {c.items.length}</option>
			{/each}
		</select>
	</label>
	<div class="newrow">
		<input
			type="text"
			placeholder="New cart name"
			bind:value={newName}
			maxlength="80"
			aria-label="New cart name"
			onkeydown={(e) => e.key === 'Enter' && create()}
		/>
		<button type="button" class="pl-btn" onclick={create}>New cart</button>
	</div>
</div>

{#if cart}
	<div class="manage">
		<input type="text" bind:value={renameValue} maxlength="80" aria-label="Rename cart" />
		<button type="button" class="pl-btn" onclick={() => carts.rename(cart.id, renameValue)}>Rename</button>
		<button type="button" class="pl-btn" onclick={() => carts.duplicate(cart.id)}>Duplicate</button>
		{#if $cartStore.carts.length > 1}
			{#if deleteId === cart.id}
				<button type="button" class="pl-btn danger" onclick={() => { carts.delete(cart.id); deleteId = null; }}>
					Confirm delete
				</button>
				<button type="button" class="pl-btn" onclick={() => (deleteId = null)}>Keep</button>
			{:else}
				<button type="button" class="pl-btn" onclick={() => (deleteId = cart.id)}>Delete</button>
			{/if}
		{/if}
		{#if cart.items.length > 0}
			{#if confirmClear}
				<button type="button" class="pl-btn danger" onclick={() => { carts.clear(); confirmClear = false; }}>
					Confirm clear ({cart.items.length})
				</button>
				<button type="button" class="pl-btn" onclick={() => (confirmClear = false)}>Keep</button>
			{:else}
				<button type="button" class="pl-btn" onclick={() => (confirmClear = true)}>Clear</button>
			{/if}
		{/if}
	</div>

	<p class="count" aria-live="polite">
		<strong>{cart.items.length} question{cart.items.length === 1 ? '' : 's'}</strong> in {cart.name}
	</p>

	{#if cart.items.length === 0}
		<div class="pl-card empty">
			<p>This cart is empty. <a href="/search">Search questions</a> and press <strong>+ Cart</strong> on any card, or open a question and use the Cart button beside its title.</p>
		</div>
	{:else}
		<div class="grid">
			{#each cart.items as item, i (`${item.paperId}/${item.number}`)}
				<CartCard
					{item}
					index={i}
					total={cart.items.length}
					onMove={(f, t) => carts.move(f, t)}
					onRemove={() => carts.remove(item.paperId, item.number)}
				/>
			{/each}
		</div>
	{/if}
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		gap: 12px;
		align-items: end;
		margin: 16px 0 4px;
	}
	.pick {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.82rem;
		font-weight: 600;
	}
	.pick select {
		min-height: 40px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-surface);
		padding: 0 10px;
		max-width: 320px;
	}
	.newrow {
		display: flex;
		gap: 8px;
	}
	.newrow input,
	.manage input {
		min-height: 40px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-surface);
		padding: 0 10px;
	}
	.manage {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin: 12px 0 4px;
	}
	.danger {
		color: var(--pl-seal);
		border-color: var(--pl-seal);
	}
	.count {
		margin: 14px 0 12px;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
		gap: 12px;
	}
	.empty a {
		font-weight: 600;
	}
</style>
