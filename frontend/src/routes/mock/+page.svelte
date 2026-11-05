<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	import Segments from '$lib/components/Segments.svelte';
	import ClassifyForm from '$lib/components/ClassifyForm.svelte';
	import FigurePanel from '$lib/components/FigurePanel.svelte';

	/**
	 * MOCK — Reading Desk UX trial. Sandbox for finalising:
	 * render-as-image, topic chips (names only), figure manager.
	 * Not linked in the sidebar; nothing here touches the main app flows.
	 */
	const isArchivist = $derived($role === 'archivist');

	let papers = $state([]);
	let questions = $state([]);
	let paperId = $state(17);
	let number = $state('1');
	let detail = $state(null);
	let figRev = $state(0);
	let showSolution = $state(false);
	let showQImage = $state(false);
	let showSImage = $state(false);
	let showTopics = $state(false);
	let editing = $state(false);
	let showFigures = $state(false);
	let qImgOk = $state(true);
	let sImgOk = $state(true);
	let loading = $state(true);
	let error = $state('');

	async function loadPapers() {
		papers = (await api.listPapers()).filter((p) => p.status === 'done');
		if (!papers.some((p) => p.id === paperId)) paperId = papers[0]?.id;
	}

	async function loadQuestions() {
		questions = await api.getQuestions(paperId);
		if (!questions.some((q) => q.number === number)) number = questions[0]?.number;
	}

	async function loadDetail() {
		loading = true;
		error = '';
		try {
			const all = await api.getQuestions(paperId);
			questions = all;
			detail = all.find((q) => q.number === number) ?? null;
			if (!detail) error = 'Question not found.';
			showTopics = false;
			editing = false;
			showFigures = false;
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function renderUrl(part) {
		return `/api/papers/${paperId}/questions/${encodeURIComponent(number)}/render?part=${part}`;
	}

	onMount(async () => {
		try {
			await loadPapers();
			await loadDetail();
		} catch (e) {
			error = e.message;
			loading = false;
		}
	});
</script>

<svelte:head><title>Mock Reading Desk - PaperLab</title></svelte:head>

<p class="pl-sub">Mock sandbox - reading-desk UX trial. Finalise here, integrate into the main app later.</p>
<h1>Mock Reading Desk</h1>

<div class="pickers">
	<label>Paper
		<select
			value={paperId}
			aria-label="Test paper"
			onchange={async (e) => {
				paperId = Number(e.currentTarget.value);
				number = '';
				showSolution = showQImage = showSImage = false;
				await loadDetail();
			}}
		>
			{#each papers as p (p.id)}
				<option value={p.id}>#{p.id} - {p.title}</option>
			{/each}
		</select>
	</label>
	<label>Question
		<select
			value={number}
			aria-label="Test question"
			onchange={async (e) => {
				number = e.currentTarget.value;
				showSolution = showQImage = showSImage = false;
				await loadDetail();
			}}
		>
			{#each questions as q (q.number)}
				<option value={q.number}>{q.number} - {q.qtype}</option>
			{/each}
		</select>
	</label>
</div>

{#if loading}
	<p class="pl-sub">Loading test question…</p>
{:else if error}
	<div class="pl-error" role="alert">{error}</div>
{:else if detail}
	<h2 class="qtitle">Question {detail.number}</h2>
	<div class="meta-row">
		<span class="typebadge">{detail.qtype}</span>
		<span class="difftext">{detail.difficulty ?? 'Not graded'}</span>
	</div>
	{#if detail.topics?.length}
		<div class="topics">
			<button type="button" class="topics-label" aria-expanded={showTopics} onclick={() => (showTopics = !showTopics)}>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
					<path d="M12 2H2v10l9.3 9.3a1 1 0 0 0 1.4 0l8.6-8.6a1 1 0 0 0 0-1.4L12 2z"/><circle cx="7" cy="7" r="1.5"/>
				</svg>
				Topics
			</button>
			{#if !showTopics}
				<span class="tchip" title={detail.topics[0].path}>{detail.topics[0].name}{detail.topics[0].auto ? ' (auto)' : ''}</span>
				{#if detail.topics.length > 1}
					<button type="button" class="morebtn" onclick={() => (showTopics = true)}>
						+{detail.topics.length - 1} more
					</button>
				{/if}
			{:else}
				<div class="allchips">
					{#each detail.topics as t (t.code)}
						<span class="tchip" title={t.path}>{t.name}{t.auto ? ' (auto)' : ''}</span>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	<div class="statement">
		<Segments segments={detail.question} bust={figRev} zoomable />
	</div>
	<div class="row">
		<button
			type="button"
			class="pl-btn"
			onclick={() => (showSolution = !showSolution)}
		>
			{showSolution ? 'Hide solution' : 'Show solution'}
		</button>
		<button type="button" class="pl-btn" onclick={() => (showQImage = !showQImage)}>
			{showQImage ? 'Hide compiled image' : 'Render question as image'}
		</button>
	</div>
	{#if showQImage}
		{#if qImgOk}
			<img
				class="compiled"
				src={renderUrl('question')}
				alt="Compiled question"
				onerror={() => (qImgOk = false)}
			/>
		{:else}
			<p class="pl-sub">TeX engine unavailable - the view above stands.</p>
		{/if}
	{/if}

	{#if showSolution}
		<div class="statement">
			<Segments segments={detail.solution} bust={figRev} zoomable />
		</div>
		<div class="row">
			<button type="button" class="pl-btn" onclick={() => (showSImage = !showSImage)}>
				{showSImage ? 'Hide compiled image' : 'Render solution as image'}
			</button>
		</div>
		{#if showSImage}
			{#if sImgOk}
				<img
					class="compiled"
					src={renderUrl('solution')}
					alt="Compiled solution"
					onerror={() => (sImgOk = false)}
				/>
			{:else}
				<p class="pl-sub">TeX engine unavailable - the view above stands.</p>
			{/if}
		{/if}
	{/if}

	{#if isArchivist}
		<div class="row">
			<button type="button" class="pl-btn" onclick={() => { editing = !editing; if (editing) showFigures = false; }}>
				{editing ? 'Done' : 'Edit classification'}
			</button>
			<button type="button" class="pl-btn" onclick={() => { showFigures = !showFigures; if (showFigures) editing = false; }}>
				{showFigures ? 'Done' : 'Manage figures'}
			</button>
		</div>
		{#if editing}
			{#key detail.paperId + detail.number}
				<ClassifyForm
					paperId={detail.paperId}
					number={detail.number}
					initial={detail}
					onSaved={(d) => (detail = d)}
				/>
			{/key}
		{/if}
		{#if showFigures}
			<FigurePanel
				paperId={detail.paperId}
				qn={detail.number}
				rev={figRev}
				onChanged={() => {
					figRev += 1;
					loadDetail();
				}}
			/>
		{/if}
	{:else}
		<p class="pl-sub">Log in as archivist to edit topics and figures.</p>
	{/if}
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	h2 {
		font-size: 1.3rem;
		margin: 16px 0 2px;
	}
	.qtitle {
		font-family: 'Roboto', Inter, system-ui, sans-serif;
		font-size: 1.75rem;
		margin: 0;
	}
	.meta-row {
		display: flex;
		align-items: center;
		gap: 12px;
		margin: 0 0 22px;
	}
	.typebadge {
		display: inline-block;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		padding: 3px 10px;
		font-size: 0.75rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--pl-ink);
	}
	.difftext {
		font-size: 0.85rem;
		color: var(--pl-ink-soft);
	}
	.topics {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		flex-wrap: wrap;
		margin: 0 0 8px;
	}
	.topics-label {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		border: none;
		background: none;
		padding: 4px 2px;
		min-height: 0;
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
		cursor: pointer;
	}
	.topics-label svg {
		width: 15px;
		height: 15px;
	}
	.topics-label:hover {
		color: var(--pl-ink);
	}
	.topics-label[aria-expanded='true'] {
		color: var(--pl-seal);
	}
	.tchip {
		display: inline-block;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		padding: 3px 10px;
		font-size: 0.8rem;
		color: var(--pl-ink);
		max-width: 100%;
	}
	.morebtn {
		border: none;
		background: none;
		padding: 4px 2px;
		min-height: 0;
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--pl-seal);
		cursor: pointer;
		white-space: nowrap;
	}
	.morebtn:hover {
		text-decoration: underline;
		text-underline-offset: 3px;
	}
	.allchips {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		flex-basis: 100%;
	}
	.allchips .tchip {
		overflow-wrap: anywhere;
	}
	.statement {
		font-size: 17.5px;
		line-height: 1.7;
		max-width: 1000px;
	}
	.statement :global(.md p) {
		margin: 0.75em 0;
	}
	.pickers {
		display: flex;
		gap: 12px;
		flex-wrap: wrap;
		margin: 12px 0;
	}
	.pickers label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.85rem;
		font-weight: 600;
	}
	.row {
		display: flex;
		gap: 8px;
		margin: 12px 0 4px;
	}
	.compiled {
		max-width: 100%;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		margin: 8px 0;
	}
</style>
