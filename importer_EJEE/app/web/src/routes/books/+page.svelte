<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api, img } from '$lib/api.js';
	import { appStatus, refreshStatus, toast } from '$lib/stores.js';
	import { estimate, CATEGORY_SHORT, STATUS_LABEL } from '$lib/labels.js';
	import { defaultFilters, saveSearchState } from '$lib/search.js';
	import FilterDropdown from '$lib/components/FilterDropdown.svelte';

	let list = $state(null);
	let error = $state('');
	let q = $state('');
	let category = $state([]);
	let open = $state(null); // slug with the convert panel open
	let range = $state('');
	let busy = $state(false);
	let limit = $state(60);

	const index = $derived($appStatus?.index);
	const shownBooks = $derived((list?.books ?? []).slice(0, limit));
	const catOpts = $derived.by(() => {
		const counts = {};
		for (const b of list?.all ?? []) counts[b.category] = (counts[b.category] ?? 0) + 1;
		return (list?.categories ?? []).filter((c) => counts[c]).map((c) => ({ value: c, count: counts[c] }));
	});

	// index.built may become true after mount (background first build).
	$effect(() => {
		if (index?.built && !list && !error) load();
	});

	let reqId = 0;
	async function load() {
		const id = ++reqId;
		try {
			const [res, all] = await Promise.all([
				api.books(q, $state.snapshot(category)),
				list?.all ? Promise.resolve(null) : api.books('', [])
			]);
			if (id !== reqId) return;
			list = { ...res, all: all?.books ?? list?.all ?? res.books };
			error = '';
		} catch (e) {
			if (id === reqId) error = e.message;
		}
	}

	let timer;
	$effect(() => {
		q;
		category.length;
		clearTimeout(timer);
		if (!index?.built) return;
		timer = setTimeout(() => {
			limit = 60;
			load();
		}, 250);
		return () => clearTimeout(timer);
	});

	function toggle(book) {
		open = open === book.slug ? null : book.slug;
		range = '';
	}

	async function convert(book) {
		busy = true;
		try {
			const r = await api.convertBook(book.slug, range.trim() || 'all');
			if (r.added.length) {
				toast(
					`Added ${r.added.length} part${r.added.length === 1 ? '' : 's'} of ${r.source} (${r.questions} questions) to the cart` +
						(r.skipped.length ? `; ${r.skipped.length} already in progress or published.` : '.'),
					'ok',
					7000
				);
			} else {
				toast('Nothing to add: those parts are already in the cart, processing or published.', 'warn');
			}
			open = null;
			await Promise.all([load(), refreshStatus()]);
		} catch (e) {
			toast(e.message, 'warn', 8000);
		} finally {
			busy = false;
		}
	}

	function browse(book) {
		saveSearchState({ filters: { ...defaultFilters(), source: [book.source] }, items: [] });
		goto('/search');
	}

	const done = (b) => b.counts.published ?? 0;
	const active = (b) => (b.counts.queued ?? 0) + (b.counts.running ?? 0);
	const pct = (n, total) => (total ? Math.round((100 * n) / total) : 0);

	onMount(refreshStatus);
</script>

<svelte:head><title>Convert books - EJEE Importer</title></svelte:head>

<h1>Convert books</h1>
<p class="pl-sub intro">
	Every source in EJEE as one card: textbooks, institute material and test-paper series, past-year and exam papers,
	olympiads. <strong>Convert book</strong> puts all its remaining 15-question parts (or the parts you name) in the
	cart; then process them in one go.
</p>

<div class="bar" role="group" aria-label="Filters">
	<label class="find">
		<span class="visually-hidden">Find a book</span>
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
			<circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
		</svg>
		<input type="search" bind:value={q} placeholder="Find a book or paper series…" />
	</label>
	<FilterDropdown label="Category" options={catOpts} bind:selected={category} />
	{#if q || category.length}
		<button type="button" class="clear-all" onclick={() => { q = ''; category = []; }}>Clear</button>
	{/if}
</div>

{#if !index}
	<p class="pl-sub">Connecting to the app…</p>
{:else if !index.built}
	<div class="pl-card">
		<p>{index.building ? `Building the EJEE index… ${index.progress} of ${index.total || '…'} sources.` : 'Set the EJEE paths in Settings to list the books.'}</p>
		{#if !index.building}<a class="pl-btn pl-btn-primary" href="/settings">Open Settings</a>{/if}
	</div>
{:else if error}
	<div class="pl-error" role="alert"><p>{error}</p><button type="button" class="pl-btn" onclick={load}>Retry</button></div>
{:else if !list}
	<p class="pl-sub">Loading…</p>
{:else}
	<p class="count" aria-live="polite">
		<strong>{list.books.length} source{list.books.length === 1 ? '' : 's'}</strong>
		· {list.books.reduce((n, b) => n + b.questions, 0).toLocaleString()} questions
		· {list.books.reduce((n, b) => n + b.parts, 0).toLocaleString()} parts
	</p>
	{#if !list.books.length}
		<div class="pl-card"><p>No source matches. Clear the filters.</p></div>
	{/if}
	<ul class="books">
		{#each shownBooks as b (b.slug)}
			{@const est = estimate(b.remaining ? Math.min(b.questions, b.remaining * 15) : 0)}
			<li class="pl-card book" class:open={open === b.slug}>
				<div class="row1">
					<img class="thumb srcimg" src={img(b.thumb, 240)} alt="" loading="lazy" />
					<div class="info">
						<p class="eyebrow">{CATEGORY_SHORT[b.category] ?? b.category}</p>
						<h2>{b.source}</h2>
						<p class="pl-sub meta">
							{b.questions.toLocaleString()} questions · {b.parts} part{b.parts === 1 ? '' : 's'}
							· {b.solution.toLocaleString()} with worked solution · {b.keyOnly.toLocaleString()} key only
						</p>
						<div class="progress" aria-label={`${done(b)} of ${b.parts} parts published`}>
							<span class="bar-done" style={`width:${pct(done(b), b.parts)}%`}></span>
							<span class="bar-active" style={`width:${pct(active(b) + (b.counts.in_cart ?? 0), b.parts)}%`}></span>
						</div>
						<p class="pl-hint">
							{done(b)} published
							{#each Object.entries(b.counts).filter(([k]) => k !== 'published') as [k, n] (k)}
								· {n} {(STATUS_LABEL[k] ?? k).toLowerCase()}
							{/each}
							· {b.remaining} remaining
						</p>
					</div>
					<div class="actions">
						<button type="button" class="pl-btn pl-btn-primary" disabled={!b.remaining} onclick={() => toggle(b)}
							aria-expanded={open === b.slug}>
							{b.remaining ? 'Convert book' : 'All parts taken'}
						</button>
						<button type="button" class="pl-btn" onclick={() => browse(b)}>Browse questions</button>
					</div>
				</div>
				{#if open === b.slug}
					<div class="panel">
						<label class="pl-field">
							Parts to convert
							<input bind:value={range} placeholder={`all (1-${b.parts})`} spellcheck="false" />
							<span class="pl-hint">Leave empty for every remaining part, or e.g. 1-5 or 1-3,8. Parts already in the cart, processing or published are skipped.</span>
						</label>
						<p class="pl-hint">
							Estimated model cost for all {b.remaining} remaining part{b.remaining === 1 ? '' : 's'}: {est.usd} ({est.inrGst} incl. GST).
						</p>
						<div class="panel-actions">
							<button type="button" class="pl-btn pl-btn-primary" disabled={busy} onclick={() => convert(b)}>
								{busy ? 'Planning…' : 'Add to cart'}
							</button>
							<button type="button" class="pl-btn" onclick={() => (open = null)}>Cancel</button>
							{#if $appStatus?.cart}<a class="pl-btn" href="/process">Go to process →</a>{/if}
						</div>
					</div>
				{/if}
			</li>
		{/each}
	</ul>
	{#if list.books.length > limit}
		<div class="more">
			<button type="button" class="pl-btn" onclick={() => (limit += 60)}>Show more · {limit} of {list.books.length}</button>
		</div>
	{/if}
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.intro {
		margin-top: 0;
		max-width: 820px;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin: 16px 0 4px;
		align-items: center;
	}
	.find {
		display: flex;
		align-items: center;
		gap: 8px;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		padding: 0 6px 0 14px;
		min-height: 40px;
		flex: 1 1 260px;
		max-width: 420px;
	}
	.find svg {
		width: 16px;
		height: 16px;
		color: var(--pl-ink-soft);
		flex-shrink: 0;
	}
	.find input {
		border: none;
		background: none;
		padding: 6px 0;
		min-height: 0;
		width: 100%;
	}
	.find input:focus {
		outline: none;
	}
	.find:focus-within {
		outline: 2px solid var(--pl-focus);
		outline-offset: 2px;
	}
	.clear-all {
		border: 1px dashed var(--pl-line);
		border-radius: var(--pl-radius-pill);
		background: none;
		color: var(--pl-seal);
		font-weight: 600;
		font-size: 0.82rem;
		padding: 8px 14px;
		min-height: 40px;
	}
	.count {
		margin: 14px 0 12px;
	}
	.books {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.book.open {
		border-color: var(--pl-seal);
		box-shadow: var(--pl-shadow-sm);
	}
	.row1 {
		display: grid;
		grid-template-columns: 120px 1fr auto;
		gap: 16px;
		align-items: center;
	}
	.thumb {
		width: 120px;
		height: 84px;
		object-fit: cover;
		object-position: top left;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: #fff;
	}
	.info {
		min-width: 0;
	}
	.info p {
		margin: 2px 0;
	}
	.eyebrow {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--pl-pine);
		font-weight: 600;
	}
	h2 {
		font-size: 1.1rem;
		overflow-wrap: anywhere;
	}
	.meta {
		font-size: 0.82rem;
	}
	.progress {
		display: flex;
		height: 6px;
		border-radius: var(--pl-radius-pill);
		background: var(--pl-raised);
		overflow: hidden;
		margin: 6px 0 2px;
		max-width: 420px;
	}
	.bar-done {
		background: var(--pl-pine);
	}
	.bar-active {
		background: var(--pl-ochre);
	}
	.actions {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.panel {
		margin-top: 14px;
		padding-top: 14px;
		border-top: 1px solid var(--pl-line);
		display: flex;
		flex-direction: column;
		gap: 10px;
		max-width: 560px;
	}
	.panel p {
		margin: 0;
	}
	.panel-actions {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.more {
		display: flex;
		justify-content: center;
		margin: 20px 0 8px;
	}
	@media (max-width: 760px) {
		.row1 {
			grid-template-columns: 1fr;
		}
		.thumb {
			width: 100%;
			height: 120px;
		}
		.actions {
			flex-direction: row;
			flex-wrap: wrap;
		}
	}
</style>
