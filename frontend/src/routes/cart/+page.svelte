<script>
	import { cartStore, activeCart, carts, cartCorrupt } from '$lib/carts.js';
	import CartCard from '$lib/components/CartCard.svelte';

	let newName = $state('');
	let renameValue = $state('');
	let creating = $state(false);
	let renaming = $state(false);
	let confirmClear = $state(false);
	let deleteArmed = $state(false);

	const cart = $derived($activeCart);

	$effect(() => {
		renameValue = cart?.name ?? '';
	});

	function startCreate() {
		creating = true;
		renaming = false;
		confirmClear = false;
		deleteArmed = false;
		newName = '';
	}
</script>

<svelte:head><title>Cart - PaperLab</title></svelte:head>

<h1>Question cart</h1>
<p class="pl-sub">
	Pick questions from Search or the reader. Carts live only in this browser —
	no server changes, no uploads. A cart tracks which questions are in, not
	their order — paragraph groups stay together as one block.
</p>

{#if $cartCorrupt}
	<div class="pl-error" role="alert">
		<strong>Saved cart data was corrupt.</strong>
		<p class="pl-mono">Started fresh; the broken copy was backed up in this browser.</p>
		<button type="button" class="pl-btn" onclick={() => cartCorrupt.set(false)}>Dismiss</button>
	</div>
{/if}

<div class="toolbar" role="toolbar" aria-label="Cart management">
	<div class="tmain">
		<label class="tselect">
			<span class="tlabel">Cart</span>
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
		{#if cart}
			<span class="tname" aria-live="polite" title={cart.name}>
				{cart.name} · <strong>{cart.items.length}</strong>
				{cart.items.length === 1 ? 'question' : 'questions'}
			</span>
		{/if}
		<div class="tactions">
			<button type="button" class="tbtn" onclick={startCreate}>New</button>
			{#if cart}
				<button
					type="button" class="tbtn"
					onclick={() => { renaming = !renaming; creating = false; }}
					aria-expanded={renaming}
				>Rename</button>
				<button type="button" class="tbtn" onclick={() => carts.duplicate(cart.id)}>Duplicate</button>
				{#if $cartStore.carts.length > 1}
					{#if deleteArmed}
						<button
							type="button" class="tbtn danger"
							onclick={() => { carts.delete(cart.id); deleteArmed = false; }}
						>Confirm delete</button>
						<button type="button" class="tbtn" onclick={() => (deleteArmed = false)}>Keep</button>
					{:else}
						<button type="button" class="tbtn" onclick={() => { deleteArmed = true; confirmClear = false; }}>Delete</button>
					{/if}
				{/if}
				{#if cart.items.length > 0}
					{#if confirmClear}
						<button
							type="button" class="tbtn danger"
							onclick={() => { carts.clear(); confirmClear = false; }}
						>Confirm clear ({cart.items.length})</button>
						<button type="button" class="tbtn" onclick={() => (confirmClear = false)}>Keep</button>
					{:else}
						<button
							type="button" class="tbtn"
							onclick={() => { confirmClear = true; deleteArmed = false; }}
						>Clear</button>
					{/if}
				{/if}
			{/if}
		</div>
	</div>
	{#if creating}
		<div class="tsub">
			<input
				type="text" placeholder="New cart name" bind:value={newName}
				maxlength="80" aria-label="New cart name"
				onkeydown={(e) => {
					if (e.key === 'Enter' && newName.trim()) { carts.create(newName.trim()); creating = false; }
					else if (e.key === 'Escape') creating = false;
				}}
			/>
			<button
				type="button" class="tbtn primary" disabled={!newName.trim()}
				onclick={() => { carts.create(newName.trim()); creating = false; }}
			>Create</button>
			<button type="button" class="tbtn" onclick={() => (creating = false)}>Cancel</button>
		</div>
	{/if}
	{#if renaming && cart}
		<div class="tsub">
			<input
				type="text" bind:value={renameValue}
				maxlength="80" aria-label="Rename cart"
				onkeydown={(e) => {
					if (e.key === 'Enter' && renameValue.trim()) { carts.rename(cart.id, renameValue); renaming = false; }
					else if (e.key === 'Escape') renaming = false;
				}}
			/>
			<button
				type="button" class="tbtn primary" disabled={!renameValue.trim()}
				onclick={() => { carts.rename(cart.id, renameValue); renaming = false; }}
			>Save</button>
			<button type="button" class="tbtn" onclick={() => (renaming = false)}>Cancel</button>
		</div>
	{/if}
</div>

{#if cart}
	{#if cart.items.length === 0}
		<div class="pl-card empty">
			<p>This cart is empty. <a href="/search">Search questions</a> and press the cart icon on any card, or open a question and use the cart button beside its title.</p>
		</div>
	{:else}
		<div class="grid">
			{#each cart.items as item (`${item.paperId}/${item.number}`)}
				<CartCard
					{item}
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
	/* 1 — compact toolbar: one row, conditional sub-row only */
	.toolbar {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		background: var(--pl-surface);
		padding: 10px 12px;
		margin: 16px 0 16px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.tmain {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px 14px;
	}
	.tselect {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 0.82rem;
		font-weight: 600;
	}
	.tlabel {
		color: var(--pl-ink-soft);
	}
	.tselect select {
		min-height: 32px;
		padding: 0 8px;
		max-width: 240px;
		font-size: 0.85rem;
	}
	.tname {
		font-size: 0.9rem;
		color: var(--pl-ink-soft);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 100%;
	}
	.tname strong {
		color: var(--pl-ink);
	}
	.tactions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-left: auto;
	}
	.tbtn {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		background: none;
		padding: 4px 12px;
		min-height: 32px;
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--pl-ink);
		cursor: pointer;
		white-space: nowrap;
	}
	.tbtn:hover {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.tbtn.primary {
		background: var(--pl-seal);
		border-color: var(--pl-seal);
		color: #fff;
	}
	.tbtn.primary:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.tbtn.danger {
		color: var(--pl-seal);
		border-color: var(--pl-seal);
		background: var(--pl-seal-soft);
	}
	.tsub {
		display: flex;
		gap: 8px;
	}
	.tsub input {
		flex: 1;
		min-width: 0;
		min-height: 32px;
		padding: 4px 10px;
		font-size: 0.85rem;
	}
	/* 4 — responsive grid: 3 / 2 / 1 */
	.grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 12px;
	}
	@media (max-width: 1100px) {
		.grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
	@media (max-width: 700px) {
		.grid {
			grid-template-columns: 1fr;
		}
		.tactions {
			margin-left: 0;
		}
	}
	.empty a {
		font-weight: 600;
	}
</style>
