<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { searchQuery } from '$lib/stores.js';
	import { fuzzyFilter } from '$lib/fuzzy.js';
	import StatCard from '$lib/components/StatCard.svelte';
	import PaperCard from '$lib/components/PaperCard.svelte';

	let papers = $state([]);
	let questionsByPaper = $state({});
	let typesByPaper = $state({});
	let loading = $state(true);
	let error = $state('');

	const filtered = $derived(
		fuzzyFilter(
			papers.filter((p) => p.status === 'done'),
			$searchQuery,
			(p) => `${p.title || ''} ${p.exam || ''} ${p.institute || ''} #${p.id}`
		)
	);
	const totalQuestions = $derived(
		Object.values(questionsByPaper).reduce((a, b) => a + b, 0)
	);

	onMount(async () => {
		try {
			papers = await api.listPapers();
			const summary = await api.getLibrarySummary().catch(() => null);
			questionsByPaper = summary?.counts ?? {};
			typesByPaper = summary?.types ?? {};
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head><title>Archive - PaperLab</title></svelte:head>

<h1>Archive</h1>
<p class="pl-sub">Pick up where you left off, or open any paper below.</p>

{#if loading}
	<p class="pl-sub">Loading papers…</p>
{:else if error}
	<div class="pl-error" role="alert">
		<strong>Could not reach the backend.</strong>
		<p class="pl-mono">{error}</p>
		<p>Start the API server, then refresh. The Streamlit app keeps working meanwhile.</p>
	</div>
{:else}
	<div class="stats">
		<StatCard label="Papers" value={papers.filter((p) => p.status === 'done').length} />
		<StatCard label="Questions" value={totalQuestions} />
		<StatCard label="Queued" value={papers.filter((p) => p.status !== 'done').length} />
		<StatCard label="Files & questions" value={papers.length} />
	</div>

	<h2>Papers</h2>
	{#if filtered.length === 0}
		<div class="pl-card">
			<p>No papers match those keywords. Try fewer or shorter words, or process new papers in Intake.</p>
		</div>
	{:else}
		<div class="wall">
			{#each filtered as paper (paper.id)}
				<PaperCard
					{paper}
					questions={questionsByPaper[paper.id] ?? 0}
					types={typesByPaper[paper.id] ?? ''}
				/>
			{/each}
		</div>
	{/if}
{/if}

<style>
	h1 {
		font-size: 2.4rem;
		margin-bottom: 4px;
	}
	.pl-sub {
		margin-top: 0;
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 12px;
		margin: 20px 0 28px;
	}
	h2 {
		font-size: 1.1rem;
		margin: 0 0 12px;
	}
	.wall {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	@media (max-width: 900px) {
		.stats {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
