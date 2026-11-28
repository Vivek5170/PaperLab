<script>
	import { onMount, tick } from 'svelte';
	import { api, img, itemHref } from '$lib/api.js';
	import { appStatus, refreshStatus } from '$lib/stores.js';
	import { answerLabel, statusLabel, CATEGORY_SHORT } from '$lib/labels.js';
	import FilterDropdown from '$lib/components/FilterDropdown.svelte';
	import TopicTreePicker from '$lib/components/TopicTreePicker.svelte';
	import PartButton from '$lib/components/PartButton.svelte';
	import ItemReader from '$lib/components/ItemReader.svelte';
	import {
		PAGE_SIZE,
		activeFilterCount,
		defaultFilters,
		loadSearchState,
		saveSearchState
	} from '$lib/search.js';

	let { lockSide = false } = $props();

	const stored = loadSearchState();

	let filters = $state(stored?.filters ?? defaultFilters());
	let items = $state(stored?.items ?? []);
	let total = $state(stored?.total ?? 0);
	let nextCursor = $state(stored?.nextCursor ?? null);
	let hasMore = $state(stored?.hasMore ?? false);
	let scrollY = $state(stored?.scrollY ?? 0);
	let qText = $state(stored?.filters?.q ?? '');

	let facets = $state(null);
	let topics = $state([]);
	let loading = $state(!(stored?.items?.length > 0));
	let loadingMore = $state(false);
	let error = $state('');
	let reqId = 0;
	let facetId = 0;

	const index = $derived($appStatus?.index);
	const indexReady = $derived(!!index?.built);
	const activeCount = $derived(activeFilterCount(filters));
	const shown = $derived(items.length);

	// Side-by-side reader (/search/side): results left, reader right.
	const sideOn = lockSide;
	let sideSel = $state(null); // { source, key }
	const isSideActive = (item) => sideOn && sideSel?.source === item.source && sideSel?.key === item.key;

	function pickSide(e, item) {
		e.preventDefault();
		sideSel = { source: item.source, key: item.key };
		if (window.matchMedia('(max-width: 900px)').matches) {
			document.getElementById('side-reader')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
	}

	$effect(() => {
		if (!sideOn) sideSel = null;
		else if (items.length > 0) {
			if (!sideSel || !items.some((i) => i.source === sideSel.source && i.key === sideSel.key)) {
				sideSel = { source: items[0].source, key: items[0].key };
			}
		}
	});

	const opts = (list) => (list ?? []).map((o) => ({ value: o.value, count: o.count }));
	const facetOpts = $derived({
		category: opts(facets?.category),
		source: opts(facets?.source),
		qtype: opts(facets?.qtype),
		difficulty: opts(facets?.difficulty),
		exam: opts(facets?.exam),
		year: opts(facets?.year),
		answer: opts(facets?.answer),
		status: opts(facets?.status)
	});

	$effect(() => {
		saveSearchState({ filters, items, total, nextCursor, hasMore, scrollY });
	});

	async function fetchPage(cursor, append) {
		const id = ++reqId;
		if (append) loadingMore = true;
		else {
			loading = true;
			error = '';
		}
		try {
			const res = await api.search($state.snapshot(filters), cursor ?? 0, PAGE_SIZE);
			if (id !== reqId) return;
			items = append ? [...items, ...res.items] : res.items;
			total = res.total;
			nextCursor = res.nextCursor;
			hasMore = res.hasMore;
		} catch (e) {
			if (id !== reqId) return;
			if (!append) error = e.message;
		} finally {
			if (id === reqId) {
				loading = false;
				loadingMore = false;
			}
		}
	}

	async function fetchFacets() {
		const id = ++facetId;
		try {
			const f = await api.facets($state.snapshot(filters));
			if (id === facetId) facets = f;
		} catch {
			/* list shows the error */
		}
	}

	function onFiltersChanged() {
		items = [];
		total = 0;
		nextCursor = null;
		hasMore = false;
		fetchPage(0, false);
		fetchFacets();
	}

	let filterSig = JSON.stringify(stored?.filters ?? defaultFilters());
	$effect(() => {
		const sig = JSON.stringify(filters);
		if (sig !== filterSig) {
			filterSig = sig;
			onFiltersChanged();
		}
	});

	// Debounced free-text search.
	let qTimer;
	$effect(() => {
		const q = qText;
		clearTimeout(qTimer);
		qTimer = setTimeout(() => {
			if (q !== filters.q) filters.q = q;
		}, 300);
		return () => clearTimeout(qTimer);
	});

	function clearAll() {
		qText = '';
		filters = defaultFilters();
	}

	// Part status changed from a card: reflect it on every card of that part.
	function partChanged(item, status) {
		items = items.map((i) => (i.slug === item.slug && i.part === item.part ? { ...i, status } : i));
		fetchFacets();
	}

	function rememberScroll() {
		scrollY = window.scrollY;
		saveSearchState({ filters, items, total, nextCursor, hasMore, scrollY });
	}

	let loadedOnce = false;
	async function init() {
		if (loadedOnce) return;
		loadedOnce = true;
		try {
			topics = await api.topics().catch(() => []);
		} finally {
			fetchFacets();
			if (items.length === 0) fetchPage(0, false);
			else {
				loading = false;
				await tick();
				if (scrollY > 0 && !sideOn) window.scrollTo(0, scrollY);
			}
		}
	}

	// Wait for the index (first run builds it in the background).
	$effect(() => {
		if (indexReady) init();
	});

	onMount(() => {
		refreshStatus();
		const onScroll = () => (scrollY = window.scrollY);
		window.addEventListener('scroll', onScroll, { passive: true });
		return () => window.removeEventListener('scroll', onScroll);
	});

	const STATUS_FORMAT = (v) => statusLabel(v);
	const ANSWER_FORMAT = (v) => (v === '(unspecified)' ? v : answerLabel(v));
</script>

<svelte:head><title>Search EJEE - EJEE Importer</title></svelte:head>
<svelte:window onpagehide={rememberScroll} />

{#snippet filterbar()}
	<div class="bar" role="group" aria-label="Filters">
		<label class="find">
			<span class="visually-hidden">Search text</span>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
				<circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
			</svg>
			<input type="search" bind:value={qText} placeholder="Title, book, paper, text…" />
		</label>
		<FilterDropdown label="Category" options={facetOpts.category} bind:selected={filters.category} />
		<FilterDropdown label="Source" options={facetOpts.source} bind:selected={filters.source} />
		<FilterDropdown label="Type" options={facetOpts.qtype} bind:selected={filters.qtype} />
		<FilterDropdown label="Difficulty" options={facetOpts.difficulty} bind:selected={filters.difficulty} />
		<FilterDropdown label="Exam" options={facetOpts.exam} bind:selected={filters.exam} />
		<FilterDropdown label="Year" options={facetOpts.year} bind:selected={filters.year} />
		<TopicTreePicker nodes={topics} counts={facets?.topicCounts ?? {}} bind:selected={filters.topic} label="Topics" />
		<FilterDropdown label="Answer" options={facetOpts.answer} bind:selected={filters.answer} format={ANSWER_FORMAT} />
		<FilterDropdown label="Status" options={facetOpts.status} bind:selected={filters.status} format={STATUS_FORMAT} />
		{#if activeCount > 0}
			<button type="button" class="clear-all" onclick={clearAll}>Clear all · {activeCount}</button>
		{/if}
	</div>
{/snippet}

{#snippet resultlist()}
	{#if !index}
		<p class="pl-sub">Connecting to the app…</p>
	{:else if !indexReady}
		<div class="pl-card">
			{#if index.building}
				<p><strong>Building the EJEE search index…</strong> {index.progress} of {index.total || '…'} sources{index.source ? ` · ${index.source}` : ''}</p>
				<progress max={index.total || 1} value={index.progress}></progress>
				<p class="pl-hint">One-time scan of the whole database (a few minutes). Search opens when it finishes.</p>
			{:else if index.error}
				<p class="pl-error">Index build failed: {index.error}</p>
				<a class="pl-btn" href="/settings">Check the EJEE paths in Settings</a>
			{:else}
				<p>Point the app at your EJEE database and uploads folder to search everything in it.</p>
				<a class="pl-btn pl-btn-primary" href="/settings">Open Settings</a>
			{/if}
		</div>
	{:else if loading}
		<p class="pl-sub">Loading questions…</p>
	{:else if error && items.length === 0}
		<div class="pl-error" role="alert">
			<strong>Search failed.</strong>
			<p class="pl-mono">{error}</p>
			<button type="button" class="pl-btn" onclick={() => fetchPage(0, false)}>Retry</button>
		</div>
	{:else}
		{#if index.stale}
			<p class="pl-error stale">The EJEE database changed since the index was built. <a href="/settings">Rebuild it in Settings</a>.</p>
		{/if}
		<p class="count" aria-live="polite">
			<strong>{total.toLocaleString()} item{total === 1 ? '' : 's'}</strong>{shown < total ? ` · showing ${shown}` : ''}
		</p>
		{#if items.length === 0}
			<div class="pl-card">
				<p>Nothing matches these filters. Clear a filter or two to widen the net.</p>
				<button type="button" class="pl-btn" onclick={clearAll}>Clear all filters</button>
			</div>
		{:else}
			<div class="grid">
				{#each items as item (`${item.source}|${item.key}`)}
					<div class="cell" class:active={isSideActive(item)}>
						<a
							class="card pl-card"
							href={itemHref(item)}
							onclick={sideOn ? (e) => pickSide(e, item) : rememberScroll}
							aria-label={item.label}
							aria-current={isSideActive(item) ? 'true' : undefined}
						>
							<span class="thumbwrap">
								<img class="thumb srcimg" src={img(item.thumb, 480)} alt="" loading="lazy" />
							</span>
							<span class="title">{item.label}</span>
							<span class="srcline">
								<span class="cat">{CATEGORY_SHORT[item.category] ?? item.category}</span>
								<span class="srcname">{item.source}</span>
							</span>
							<span class="meta">
								<span class="chips">
									{#if item.difficulty}
										<span class={`chip diff-${item.difficulty.toLowerCase()}`}>{item.difficulty}</span>
									{/if}
									{#if item.qtype}<span class="chip type" title={item.qtype}>{item.qtype}</span>{/if}
									<span class="chip ans" title={answerLabel(item.answer)}>
										{item.answer === 'solution' ? 'Sol' : item.answer === 'key' ? 'Key' : 'Q only'}
									</span>
								</span>
								<PartButton {item} onchange={(s) => partChanged(item, s)} />
							</span>
						</a>
					</div>
				{/each}
			</div>
			{#if hasMore}
				<div class="more">
					<button type="button" class="pl-btn" disabled={loadingMore} onclick={() => fetchPage(nextCursor, true)}>
						{loadingMore ? 'Loading…' : `Load more · ${shown} of ${total.toLocaleString()}`}
					</button>
				</div>
			{/if}
		{/if}
	{/if}
{/snippet}

{#snippet readerpane()}
	<aside class="reader" id="side-reader" aria-label="Item preview">
		{#if sideSel}
			<div class="readerbar">
				<span class="pl-mono">{sideSel.key}</span>
				<a class="openfull" href={itemHref(sideSel)}>Open full page</a>
			</div>
			{#key `${sideSel.source}|${sideSel.key}`}
				<ItemReader source={sideSel.source} itemKey={sideSel.key} compact onpick={(p) => (sideSel = p)} />
			{/key}
		{:else}
			<p class="pl-sub">Select an item to preview it here.</p>
		{/if}
	</aside>
{/snippet}

{#if sideOn}
	<div class="pagewrap focus">
		<div class="wsbar">
			<a class="back" href="/search">← Back</a>
			{@render filterbar()}
		</div>
		<div class="dual">
			<section class="results" aria-label="Results">
				{@render resultlist()}
			</section>
			{@render readerpane()}
		</div>
	</div>
{:else}
	<div class="pagewrap">
		<h1>Search EJEE</h1>
		<p class="pl-sub">
			Every question in your EJEE database{index?.items ? ` — ${index.items.toLocaleString()} from ${index.sources} sources` : ''}:
			textbooks, institute study material and test papers, past-year and exam papers, olympiads. Add a 15-question
			part to the cart to convert it.
		</p>
		{@render filterbar()}
		{@render resultlist()}
	</div>
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.pl-sub {
		margin-top: 0;
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
		flex: 1 1 220px;
		max-width: 340px;
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
		white-space: nowrap;
	}
	.clear-all:hover {
		background: var(--pl-seal-soft);
	}
	.count {
		margin: 14px 0 12px;
	}
	.stale {
		margin: 12px 0 0;
		font-size: 0.85rem;
	}
	progress {
		width: 100%;
		accent-color: var(--pl-pine);
	}
	.pagewrap.focus {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.wsbar {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		padding: 10px 20px;
		background: var(--pl-surface);
		border-bottom: 1px solid var(--pl-line);
		flex-shrink: 0;
	}
	.wsbar .back {
		font-weight: 600;
		font-size: 0.85rem;
		white-space: nowrap;
	}
	.wsbar .bar {
		margin: 0;
		flex: 1;
		min-width: 0;
	}
	.dual {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: 1fr 1fr;
		align-items: stretch;
	}
	.dual .results {
		min-height: 0;
		overflow-y: auto;
		padding: 16px 20px 24px;
	}
	.dual .count {
		margin-top: 0;
	}
	.dual .grid {
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
	}
	.cell.active .card {
		border-color: var(--pl-seal);
		box-shadow: var(--pl-shadow-sm);
	}
	.reader {
		min-height: 0;
		overflow-y: auto;
		border-left: 1px solid var(--pl-line);
		padding: 16px 20px 24px 24px;
		min-width: 0;
	}
	.readerbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 8px;
		font-size: 0.82rem;
		color: var(--pl-ink-soft);
	}
	.readerbar .pl-mono {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.openfull {
		font-weight: 600;
		font-size: 0.82rem;
		white-space: nowrap;
	}
	@media (max-width: 900px) {
		.pagewrap.focus {
			flex: none;
			display: block;
			padding-bottom: 24px;
		}
		.wsbar {
			position: sticky;
			top: 0;
			z-index: 30;
		}
		.dual {
			display: block;
		}
		.dual .results {
			overflow: visible;
		}
		.reader {
			overflow: visible;
			border-left: none;
			padding: 20px;
			border-top: 1px solid var(--pl-line);
			margin-top: 8px;
		}
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 12px;
	}
	.cell {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.card {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 8px;
		text-decoration: none;
		color: inherit;
		padding: 12px;
	}
	.card:hover {
		box-shadow: var(--pl-shadow-sm);
		border-color: var(--pl-seal);
	}
	.thumbwrap {
		display: block;
		height: 150px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: #fff;
		overflow: hidden;
	}
	.thumb {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: cover;
		object-position: top left;
	}
	.title {
		font-weight: 600;
		font-size: 0.88rem;
		line-height: 1.4;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.srcline {
		display: flex;
		gap: 6px;
		align-items: baseline;
		font-size: 0.75rem;
		color: var(--pl-ink-soft);
		min-width: 0;
	}
	.cat {
		flex-shrink: 0;
		font-weight: 600;
		color: var(--pl-pine);
	}
	.srcname {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		border-top: 1px solid var(--pl-line);
		padding-top: 8px;
		margin-top: auto;
	}
	.chips {
		display: flex;
		gap: 4px;
		min-width: 0;
		overflow: hidden;
	}
	.chip {
		border-radius: 6px;
		padding: 2px 6px;
		font-size: 0.7rem;
		font-weight: 600;
		background: var(--pl-raised);
		white-space: nowrap;
	}
	.chip.type {
		font-family: var(--pl-font-mono);
		font-weight: 500;
		max-width: 90px;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.diff-easy {
		background: var(--pl-pine-soft);
		color: var(--pl-pine);
	}
	.diff-medium {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.diff-hard,
	.diff-olympiad {
		background: var(--pl-seal-soft);
		color: var(--pl-seal);
	}
	.more {
		display: flex;
		justify-content: center;
		margin: 20px 0 8px;
	}
	@media (max-width: 640px) {
		.grid {
			grid-template-columns: 1fr;
		}
		.find {
			max-width: none;
		}
	}
</style>
