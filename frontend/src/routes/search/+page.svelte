<script>
	import { onMount, tick } from 'svelte';
	import { api } from '$lib/api.js';
	import FilterDropdown from '$lib/components/FilterDropdown.svelte';
	import TopicTreePicker from '$lib/components/TopicTreePicker.svelte';
	import AddToCart from '$lib/components/AddToCart.svelte';
	import { qtypeLabel } from '$lib/qtypes.js';
	import {
		PAGE_SIZE,
		activeFilterCount,
		defaultFilters,
		loadSearchState,
		saveSearchState
	} from '$lib/search.js';

	const stored = loadSearchState();

	let filters = $state(stored?.filters ?? defaultFilters());
	let items = $state(stored?.items ?? []);
	let total = $state(stored?.total ?? 0);
	let nextCursor = $state(stored?.nextCursor ?? null);
	let hasMore = $state(stored?.hasMore ?? false);
	let scrollY = $state(stored?.scrollY ?? 0);

	let facets = $state(null);
	let topics = $state([]);
	let loading = $state(!(stored?.items?.length > 0));
	let loadingMore = $state(false);
	let error = $state('');
	let reqId = $state(0);

	const activeCount = $derived(activeFilterCount(filters));
	const shown = $derived(items.length);

	const facetOpts = $derived.by(() => {
		if (!facets) return { qtype: [], difficulty: [], exam: [], institute: [], year: [] };
		return {
			qtype: facets.qtypes.map((o) => ({ value: o.value, count: o.count })),
			difficulty: facets.difficulties.map((o) => ({ value: o.value, count: o.count })),
			exam: facets.exams.map((o) => ({ value: o.value, count: o.count })),
			institute: facets.institutes.map((o) => ({ value: o.name, count: o.count })),
			year: facets.years.map((o) => ({ value: String(o.value), count: o.count }))
		};
	});
	const topicCounts = $derived(facets?.topicSubtreeCounts ?? facets?.topicCounts ?? {});
	const gradedCount = $derived(
		facets ? facets.difficulties.reduce((n, o) => n + o.count, 0) : 0
	);

	function formatChapters(item) {
		const ch = item.chapters ?? [];
		if (ch.length === 0) return '';
		return ch.join(' · ') + (item.chapterOverflow > 0 ? ` +${item.chapterOverflow}` : '');
	}

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
			const res = await api.searchQuestions(filters, { limit: PAGE_SIZE, cursor });
			if (id !== reqId) return; // stale: filters changed mid-flight
			if (append) items = [...items, ...res.items];
			else items = res.items;
			total = res.total;
			nextCursor = res.nextCursor;
			hasMore = res.hasMore;
		} catch (e) {
			if (id !== reqId) return;
			// Stale cursor (filters changed elsewhere): restart cleanly once.
			if (cursor && String(e.message).startsWith('400') && !append) {
				nextCursor = null;
				return fetchPage(null, false);
			}
			if (!append) error = e.message;
		} finally {
			if (id === reqId) {
				loading = false;
				loadingMore = false;
			}
		}
	}

	function onFiltersChanged() {
		items = [];
		total = 0;
		nextCursor = null;
		hasMore = false;
		fetchPage(null, false);
	}

	// Any filter edit restarts from page one.
	let filterSig = $state(JSON.stringify(stored?.filters ?? defaultFilters()));
	$effect(() => {
		const sig = JSON.stringify(filters);
		if (sig !== filterSig) {
			filterSig = sig;
			onFiltersChanged();
		}
	});

	function clearAll() {
		filters = defaultFilters();
	}

	function rememberScroll() {
		scrollY = window.scrollY;
		saveSearchState({ filters, items, total, nextCursor, hasMore, scrollY });
	}

	function onScroll() {
		scrollY = window.scrollY;
	}

	onMount(async () => {
		window.addEventListener('scroll', onScroll, { passive: true });
		try {
			const [f, t] = await Promise.all([
				api.getSearchFacets(),
				api.getTopics().catch(() => [])
			]);
			facets = f;
			topics = t;
		} catch (e) {
			if (items.length === 0) error = e.message;
		} finally {
			if (items.length === 0 && !error) {
				fetchPage(null, false);
			} else {
				loading = false;
				await tick();
				if (scrollY > 0) window.scrollTo(0, scrollY);
			}
		}
		return () => window.removeEventListener('scroll', onScroll);
	});
</script>

<svelte:head><title>Search Questions - PaperLab</title></svelte:head>
<svelte:window onpagehide={rememberScroll} />

<h1>Search questions</h1>
<p class="pl-sub">Filter {total > 0 ? `${total} ` : ''}questions by type, topic, source, exam, year or difficulty.</p>

<div class="bar" role="group" aria-label="Question filters">
	<FilterDropdown label="Type" options={facetOpts.qtype} bind:selected={filters.qtype} format={qtypeLabel} />
	<FilterDropdown label="Difficulty" options={facetOpts.difficulty} bind:selected={filters.difficulty} />
	<FilterDropdown label="Source" options={facetOpts.institute} bind:selected={filters.institute} />
	<FilterDropdown label="Exam" options={facetOpts.exam} bind:selected={filters.exam} />
	<FilterDropdown label="Year" options={facetOpts.year} bind:selected={filters.year} />
	<TopicTreePicker nodes={topics} counts={topicCounts} bind:selected={filters.topic} />
	{#if activeCount > 0}
		<button type="button" class="clear-all" onclick={clearAll}>
			Clear all · {activeCount}
		</button>
	{/if}
</div>
{#if facets && facets.ungradedDifficulty > 0}
	<p class="pl-sub note">Difficulty is graded on {gradedCount} of {gradedCount + facets.ungradedDifficulty} questions — ungraded ones appear only when no difficulty filter is active.</p>
{/if}

{#if loading}
	<p class="pl-sub">Loading questions…</p>
{:else if error && items.length === 0}
	<div class="pl-error" role="alert">
		<strong>Could not reach the backend.</strong>
		<p class="pl-mono">{error}</p>
		<button type="button" class="pl-btn" onclick={() => fetchPage(null, false)}>Retry</button>
	</div>
{:else}
	<p class="count" aria-live="polite"><strong>{total} question{total === 1 ? '' : 's'}</strong>{shown < total ? ` · showing ${shown}` : ''}</p>
	{#if items.length === 0}
		<div class="pl-card">
			<p>No questions match these filters. Clear a filter or two to widen the net.</p>
			<button type="button" class="pl-btn" onclick={clearAll}>Clear all filters</button>
		</div>
	{:else}
		<div class="grid">
			{#each items as item (`${item.paperId}/${item.number}`)}
				<div class="cell">
					<a
						class="card pl-card"
						href={`/search/${item.paperId}/${encodeURIComponent(item.number)}`}
						onclick={rememberScroll}
						aria-label={`Paper ${item.paperId}, question ${item.number}`}
					>
						<span class="top">
							<span class="preview">{item.preview || 'No text preview available.'}</span>
							{#if item.thumb}
								<img class="thumb" src={item.thumb} alt="" loading="lazy" />
							{/if}
						</span>
						<span class="chapters">
							{#if item.chapters?.length}
								{formatChapters(item)}
							{:else}
								<span class="untagged">Untagged</span>
							{/if}
						</span>
						<span class="meta">
							<span class="paperline">{item.paper?.exam ?? ''}{item.paper?.year ? ` · ${item.paper.year}` : ''}</span>
							<span class="chips">
								{#if item.difficulty}
									<span class={`chip diff-${item.difficulty.toLowerCase()}`}>{item.difficulty}</span>
								{/if}
								<span class="chip type" title={item.qtype}>{qtypeLabel(item.qtype)}</span>
								<AddToCart
									item={{
										paperId: item.paperId,
										number: item.number,
										qtype: item.qtype,
										difficulty: item.difficulty,
										preview: item.preview,
										thumb: item.thumb,
										exam: item.paper?.exam ?? '',
										year: item.paper?.year ?? null,
										institute: item.paper?.institute ?? ''
									}}
							 />
							</span>
						</span>
					</a>
				</div>
			{/each}
		</div>
		{#if hasMore}
			<div class="more">
				<button type="button" class="pl-btn" disabled={loadingMore} onclick={() => fetchPage(nextCursor, true)}>
					{loadingMore ? 'Loading…' : `Load more · ${shown} of ${total}`}
				</button>
			</div>
		{/if}
	{/if}
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.pl-sub {
		margin-top: 0;
	}
	.note {
		font-size: 0.8rem;
		margin: 8px 0 0;
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin: 16px 0 4px;
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
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
		gap: 12px;
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: 10px;
		text-decoration: none;
		color: inherit;
		padding: 14px;
	}
	.card:hover {
		box-shadow: var(--pl-shadow-sm);
		border-color: var(--pl-seal);
	}
	.cell {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.cell .card {
		flex: 1;
	}
	.top {
		display: flex;
		gap: 10px;
		align-items: flex-start;
		min-height: 72px;
	}
	.preview {
		flex: 1;
		min-width: 0;
		font-size: 0.86rem;
		line-height: 1.5;
		display: -webkit-box;
		-webkit-line-clamp: 4;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.thumb {
		width: 76px;
		height: 76px;
		object-fit: cover;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-raised);
		flex-shrink: 0;
	}
	.chapters {
		font-weight: 600;
		font-size: 0.9rem;
	}
	.untagged {
		color: var(--pl-ink-soft);
		font-weight: 500;
		font-size: 0.82rem;
	}
	.meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		border-top: 1px solid var(--pl-line);
		padding-top: 10px;
	}
	.paperline {
		font-size: 0.75rem;
		color: var(--pl-ink-soft);
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.chips {
		display: flex;
		gap: 6px;
		flex-shrink: 0;
		align-items: center;
	}
	.chip {
		border-radius: 6px;
		padding: 2px 8px;
		font-size: 0.72rem;
		font-weight: 600;
	}
	.chip.type {
		background: var(--pl-raised);
		font-family: var(--pl-font-mono);
		font-weight: 500;
	}
	.diff-easy {
		background: var(--pl-pine-soft);
		color: var(--pl-pine);
	}
	.diff-medium {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.diff-hard {
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
	}
</style>
