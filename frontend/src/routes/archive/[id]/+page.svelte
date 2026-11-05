<script>
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	import Segments from '$lib/components/Segments.svelte';
	import ClassifyForm from '$lib/components/ClassifyForm.svelte';

	const id = $derived($page.params.id);
	const isArchivist = $derived($role === 'archivist');

	let paper = $state(null);
	let questions = $state([]);
	let current = $state('');
	let showSolution = $state(false);
	let editing = $state(false);
	let loading = $state(true);
	let error = $state('');

	let currentQ = $state(null);

	async function refresh() {
		[paper, questions] = await Promise.all([api.getPaper(id), api.getQuestions(id)]);
		if (!questions.some((q) => q.number === current)) {
			current = questions[0]?.number ?? '';
		}
		currentQ = questions.find((q) => q.number === current) ?? null;
	}

	function pick(qn) {
		current = qn;
		currentQ = questions.find((q) => q.number === qn) ?? null;
		showSolution = false;
	}

	onMount(async () => {
		try {
			await refresh();
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head><title>{paper ? paper.title : 'Reading Desk'} - PaperLab</title></svelte:head>

<a class="back" href="/archive">Back to Archive</a>

{#if loading}
	<p class="pl-sub">Loading paper…</p>
{:else if error}
	<div class="pl-error" role="alert">
		<strong>Could not load this paper.</strong>
		<p class="pl-mono">{error}</p>
	</div>
{:else}
		<h1>{paper.title || `Paper ${paper.id}`}</h1>
	<p class="pl-mono pl-sub">
		Paper #{paper.id} - {paper.exam || 'Unknown exam'} - {questions.length} questions
	</p>

	<div class="desk">
		<nav class="index" aria-label="Questions">
			{#if questions.length > 40}
				<select
					value={current}
					aria-label="Choose a question"
					onchange={(e) => pick(e.currentTarget.value)}
				>
					{#each questions as q (q.number)}
						<option value={q.number}>{q.number} - {q.qtype}</option>
					{/each}
				</select>
			{:else}
				{#each questions as q (q.number)}
					<button
						type="button"
						class="qbtn"
						class:active={q.number === current}
						aria-current={q.number === current ? 'true' : undefined}
						onclick={() => pick(q.number)}
					>
						<span class="pl-mono">{q.number}</span>
						<span class="qtype">{q.qtype}</span>
					</button>
				{/each}
			{/if}
		</nav>

		<article class="pane">
			{#if currentQ}
				<h2>Question {currentQ.number}</h2>
				<p class="pl-sub">
					Type: {currentQ.qtype}{currentQ.difficulty
						? ` - Difficulty: ${currentQ.difficulty}`
						: ' - Difficulty: not graded'}
				</p>
				{#if currentQ.topics?.length}
					<p>
						{#each currentQ.topics as t, i (t.code)}
							<span class="pl-chip">{i === 0 ? 'Primary: ' : 'Also: '}{t.path}{t.auto ? ' (auto)' : ''}</span>
						{/each}
					</p>
				{/if}
				<svelte:boundary>
					<Segments segments={currentQ.question} />
					{#snippet failed()}
						<p class="pl-error" role="alert">Could not display this question. The data is unchanged.</p>
					{/snippet}
				</svelte:boundary>
				<button
					type="button"
					class="pl-btn"
					onclick={() => (showSolution = !showSolution)}
				>
					{showSolution ? 'Hide solution' : 'Show solution'}
				</button>
				{#if showSolution}
					<div class="solution">
						<svelte:boundary>
							<Segments segments={currentQ.solution} />
							{#snippet failed()}
								<p class="pl-error" role="alert">Could not display this solution.</p>
							{/snippet}
						</svelte:boundary>
					</div>
				{/if}
				{#if isArchivist}
					<button
						type="button"
						class="pl-btn"
						onclick={() => (editing = !editing)}
					>
						{editing ? 'Done' : 'Edit classification'}
					</button>
					{#if editing}
						{#key currentQ.paperId + currentQ.number}
						<ClassifyForm
							paperId={id}
							number={currentQ.number}
							initial={currentQ}
							onSaved={(detail) => {
								questions = questions.map((q) =>
									q.number === detail.number ? detail : q
								);
								currentQ = detail;
							}}
						/>
						{/key}
					{/if}
				{/if}
			{/if}
		</article>
	</div>
{/if}

<style>
	.back {
		display: inline-block;
		margin-bottom: 12px;
		font-weight: 600;
		font-size: 0.85rem;
	}
	h1 {
		font-size: 2rem;
		margin-bottom: 2px;
	}
	.desk {
		display: grid;
		grid-template-columns: 240px 1fr;
		gap: 16px;
		margin-top: 20px;
		align-items: start;
	}
	.index {
		display: flex;
		flex-direction: column;
		gap: 2px;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		padding: 8px;
		max-height: 70dvh;
		overflow-y: auto;
	}
	.qbtn {
		display: flex;
		gap: 10px;
		align-items: baseline;
		text-align: left;
		border: none;
		border-left: 3px solid transparent;
		background: none;
		border-radius: 8px;
		padding: 8px 10px;
		min-height: 44px;
	}
	.qbtn:hover {
		background: var(--pl-raised);
	}
	.qbtn.active {
		background: var(--pl-raised);
		border-left-color: var(--pl-seal);
		font-weight: 600;
	}
	.qtype {
		color: var(--pl-ink-soft);
		font-size: 0.8rem;
	}
	.pane {
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		padding: 24px;
		max-width: 75ch;
	}
	.pane h2 {
		font-size: 1.3rem;
		margin-bottom: 2px;
	}
	.solution {
		border-top: 1px solid var(--pl-line);
		padding-top: 14px;
	}
	.pane .pl-btn {
		margin-top: 8px;
	}
	@media (max-width: 760px) {
		.desk {
			grid-template-columns: 1fr;
		}
	}
</style>
