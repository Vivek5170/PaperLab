<script>
	import { onMount } from 'svelte';
	import { api, img } from '$lib/api.js';
	import { refreshStatus, toast, appStatus } from '$lib/stores.js';
	import { estimate, CATEGORY_SHORT } from '$lib/labels.js';
	import SetupNotice from '$lib/components/SetupNotice.svelte';
	import { defaultFilters, saveSearchState } from '$lib/search.js';

	let data = $state(null);
	let error = $state('');
	let busy = $state(false);

	const est = $derived(estimate(data?.questions ?? 0));
	const missing = $derived($appStatus?.missing ?? []);

	async function load() {
		error = '';
		try {
			data = await api.cart();
		} catch (e) {
			error = e.message;
		}
	}

	async function remove(row) {
		busy = true;
		try {
			data = await api.removePart(row.slug, row.part);
			refreshStatus();
		} catch (e) {
			toast(e.message, 'warn');
		} finally {
			busy = false;
		}
	}

	async function clearAll() {
		if (!confirm('Remove every part from the cart?')) return;
		busy = true;
		try {
			data = await api.clearCart();
			refreshStatus();
		} catch (e) {
			toast(e.message, 'warn');
		} finally {
			busy = false;
		}
	}

	onMount(load);

	const answerSummary = (a = {}) =>
		[
			a.solution ? `${a.solution} with worked solution` : '',
			a.key ? `${a.key} answer key only` : '',
			a.none ? `${a.none} question only` : ''
		]
			.filter(Boolean)
			.join(' · ');
</script>

<svelte:head><title>Cart - EJEE Importer</title></svelte:head>

<div class="head">
	<div>
		<h1>Cart</h1>
		<p class="pl-sub">
			Parts waiting to be converted. Each part becomes one PaperLab paper, “Book — Part N”, of up to 15 questions.
		</p>
	</div>
	{#if data?.items?.length}
		<div class="actions">
			<button type="button" class="pl-btn" disabled={busy} onclick={clearAll}>Clear cart</button>
			<a class="pl-btn pl-btn-primary" href="/process">Go to process →</a>
		</div>
	{/if}
</div>

{#if error}
	<div class="pl-error" role="alert">
		<p>{error}</p>
		<button type="button" class="pl-btn" onclick={load}>Retry</button>
	</div>
{:else if !data}
	<p class="pl-sub">Loading…</p>
{:else if !data.items.length}
	<div class="pl-card empty">
		<p>The cart is empty. Find a book, paper or sheet in Search and add its parts.</p>
		<a class="pl-btn pl-btn-primary" href="/search">Search EJEE</a>
	</div>
{:else}
	<section class="summary pl-card" aria-label="Cart summary">
		<div>
			<span class="big">{data.items.length}</span> part{data.items.length === 1 ? '' : 's'}
			· <span class="big">{data.questions}</span> questions
		</div>
		<div class="pl-sub">
			Estimated model cost {est.usd} ({est.inrGst} incl. 18% GST), from the measured pilot range. Actual cost is
			shown per part while it runs.
		</div>
	</section>

	{#if missing.length}
		<SetupNotice action="process this cart" />
	{/if}

	<ul class="list">
		{#each data.items as row (`${row.slug}/${row.part}`)}
			<li class="pl-card part">
				<div class="thumbs" aria-hidden="true">
					{#each row.thumbs ?? [] as rid (rid)}
						<img class="srcimg" src={img(rid, 240)} alt="" loading="lazy" />
					{/each}
				</div>
				<div class="info">
					<p class="eyebrow">{CATEGORY_SHORT[row.category] ?? row.category ?? ''}{row.parts ? ` · part ${row.part} of ${row.parts}` : ''}</p>
					<h2>{row.source} — Part {row.part}</h2>
					<p class="pl-sub range">{row.first ?? ''}{row.last && row.last !== row.first ? ` → ${row.last}` : ''}</p>
					<p class="pl-sub">{row.questions} questions{row.answers ? ` · ${answerSummary(row.answers)}` : ''}</p>
				</div>
				<div class="side">
					<a class="pl-btn" href={`/search/side`} onclick={() => {
						saveSearchState({ filters: { ...defaultFilters(), source: [row.source], status: ['in_cart'] }, items: [] });
					}}>Preview</a>
					<button type="button" class="pl-btn" disabled={busy} onclick={() => remove(row)}>Remove</button>
				</div>
			</li>
		{/each}
	</ul>

	<div class="foot">
		<a class="pl-btn" href="/search">Add more</a>
		<a class="pl-btn pl-btn-primary" href="/process">Go to process →</a>
	</div>
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		gap: 16px;
		flex-wrap: wrap;
		margin-bottom: 16px;
	}
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.head .pl-sub {
		margin: 0;
		max-width: 620px;
	}
	.actions,
	.foot {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.foot {
		justify-content: flex-end;
		margin-top: 16px;
	}
	.empty {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 12px;
	}
	.empty p {
		margin: 0;
	}
	.summary {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-bottom: 8px;
	}
	.summary .pl-sub {
		font-size: 0.85rem;
	}
	.big {
		font-family: var(--pl-font-display);
		font-size: 1.4rem;
		font-weight: 600;
	}
	.list {
		list-style: none;
		margin: 12px 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.part {
		display: grid;
		grid-template-columns: 220px 1fr auto;
		gap: 16px;
		align-items: center;
	}
	.thumbs {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 4px;
	}
	.thumbs img {
		width: 100%;
		height: 56px;
		object-fit: cover;
		object-position: top left;
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		background: #fff;
	}
	.info {
		min-width: 0;
	}
	.info p {
		margin: 2px 0;
		font-size: 0.85rem;
	}
	.eyebrow {
		font-size: 0.72rem !important;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--pl-pine);
		font-weight: 600;
	}
	h2 {
		font-size: 1.15rem;
	}
	.range {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.side {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	@media (max-width: 760px) {
		.part {
			grid-template-columns: 1fr;
		}
		.side {
			flex-direction: row;
		}
	}
</style>
