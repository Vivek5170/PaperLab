<script>
	/**
	 * Shared question reader (Archive + Search detail). Extracted verbatim
	 * from the archive reader: segments, figures, solutions, edit
	 * classification, permissions and API behavior are identical.
	 * Wrappers supply the paper id, optional initial question, and the
	 * back link target/label.
	 */
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	import Segments from '$lib/components/Segments.svelte';
	import ClassifyForm from '$lib/components/ClassifyForm.svelte';
	import FigurePanel from '$lib/components/FigurePanel.svelte';
	import AddToCart from '$lib/components/AddToCart.svelte';
	import { qtypeLabel } from '$lib/qtypes.js';

	let { paperId, initialQ = null, backHref = '/archive', backLabel = 'Back to Archive' } = $props();

	const isArchivist = $derived($role === 'archivist');

	let paper = $state(null);
	let questions = $state([]);
	let current = $state('');
	let showSolution = $state(false);
	let showTopics = $state(false);
	let showQImage = $state(false);
	let showSImage = $state(false);
	let qImgOk = $state(true);
	let sImgOk = $state(true);
	let editing = $state(false);
	let showFigures = $state(false);
	let figRev = $state(0);
	let loading = $state(true);
	let error = $state('');
	let mobTab = $state('question'); // mobile only: 'list' | 'question'

	let currentQ = $state(null);

	function plainPreview(segs) {
		for (const s of segs ?? []) {
			if (s?.kind === 'text' && typeof s.html === 'string') {
				const t = s.html
					.replace(/<[^>]*>/g, ' ')
					.replace(/\s+/g, ' ')
					.trim();
				if (t) return t.slice(0, 300);
			}
		}
		return '';
	}

	function firstFigUrl(segs) {
		for (const s of segs ?? []) {
			if (s?.kind === 'fig' && s.url) return s.url;
		}
		return null;
	}

	const cartItem = $derived(
		currentQ
			? {
					paperId: currentQ.paperId,
					number: currentQ.number,
					qtype: currentQ.qtype,
					difficulty: currentQ.difficulty ?? null,
					preview: plainPreview(currentQ.question),
					thumb: firstFigUrl(currentQ.question),
					exam: paper?.exam ?? '',
					year: null,
					institute: paper?.institute ?? ''
				}
			: null
	);

	const editHref = $derived(
		currentQ
			? `/lab/edit/${paperId}/${encodeURIComponent(currentQ.number)}?part=question&back=${encodeURIComponent(backHref)}`
			: ''
	);

	function renderUrl(part) {
		return `/api/papers/${paperId}/questions/${encodeURIComponent(current)}/render?part=${part}`;
	}

	async function refresh() {
		[paper, questions] = await Promise.all([api.getPaper(paperId), api.getQuestions(paperId)]);
		if (!questions.some((q) => q.number === current)) {
			current =
				(initialQ && questions.some((q) => q.number === initialQ)
					? initialQ
					: (questions[0]?.number ?? ''));
		}
		currentQ = questions.find((q) => q.number === current) ?? null;
	}

	function pick(qn) {
		current = qn;
		currentQ = questions.find((q) => q.number === qn) ?? null;
		showSolution = false;
		showTopics = false;
		showQImage = false;
		showSImage = false;
		qImgOk = true;
		sImgOk = true;
		editing = false;
		showFigures = false;
		mobTab = 'question';
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

<a class="back" href={backHref}>{backLabel}</a>

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

	<div class="mobtabs" role="tablist" aria-label="Reader view">
		<button type="button" role="tab" aria-selected={mobTab === 'list'} class:active={mobTab === 'list'} onclick={() => (mobTab = 'list')}>List</button>
		<button type="button" role="tab" aria-selected={mobTab === 'question'} class:active={mobTab === 'question'} onclick={() => (mobTab = 'question')}>Question</button>
	</div>

	<div class="desk" data-view={mobTab}>
		<nav class="index" aria-label="Questions">
			{#if questions.length > 40}
				<select
					value={current}
					aria-label="Choose a question"
					onchange={(e) => pick(e.currentTarget.value)}
				>
					{#each questions as q (q.number)}
						<option value={q.number}>{q.number}</option>
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
						title={`Question ${q.number}`}
					>
						<span class="pl-mono">{q.number}</span>
					</button>
				{/each}
			{/if}
		</nav>

		<article class="pane">
			{#if currentQ}
				<div class="qtitle-row">
					<h2 class="qtitle">Question {currentQ.number}</h2>
					{#if cartItem}
						<span class="cartslot"><AddToCart item={cartItem} variant="tool" /></span>
					{/if}
					{#if isArchivist}
						<a
							class="editlink"
							href={editHref}
							title="Edit TeX (experimental)"
							aria-label={`Edit TeX for question ${currentQ.number} (experimental)`}
						>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
						</a>
					{/if}
				</div>
				<div class="meta-row">
					<span class="typebadge" title={currentQ.qtype}>{qtypeLabel(currentQ.qtype)}</span>
					<span class="difftext">{currentQ.difficulty ?? 'Not graded'}</span>
				</div>
				{#if currentQ.topics?.length}
					<div class="topics">
						<button type="button" class="topics-label" aria-expanded={showTopics} onclick={() => (showTopics = !showTopics)}>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 2H2v10l9.3 9.3a1 1 0 0 0 1.4 0l8.6-8.6a1 1 0 0 0 0-1.4L12 2z"/><circle cx="7" cy="7" r="1.5"/></svg>
							Topics
						</button>
						{#if !showTopics}
							<span class="tchip" title={currentQ.topics[0].path}>{currentQ.topics[0].name}{currentQ.topics[0].auto ? ' (auto)' : ''}</span>
							{#if currentQ.topics.length > 1}
								<button type="button" class="morebtn" onclick={() => (showTopics = true)}>+{currentQ.topics.length - 1} more</button>
							{/if}
						{:else}
							<div class="allchips">
								{#each currentQ.topics as tt (tt.code)}
									<span class="tchip" title={tt.path}>{tt.name}{tt.auto ? ' (auto)' : ''}</span>
								{/each}
							</div>
						{/if}
					</div>
				{/if}
				<div class="statement">
					<svelte:boundary>
						<Segments segments={currentQ.question} bust={figRev} zoomable />
						{#snippet failed()}
							<p class="pl-error" role="alert">Could not display this question. The data is unchanged.</p>
						{/snippet}
					</svelte:boundary>
				</div>
				<div class="row">
					<button type="button" class="pl-btn" onclick={() => (showSolution = !showSolution)}>
						{showSolution ? 'Hide solution' : 'Show solution'}
					</button>
					<button type="button" class="pl-btn" onclick={() => { showQImage = !showQImage; qImgOk = true; }}>
						{showQImage ? 'Hide compiled image' : 'Render question as image'}
					</button>
				</div>
				{#if showQImage}
					{#if qImgOk}
						<img class="compiled" src={renderUrl('question')} alt="Compiled question" onerror={() => (qImgOk = false)} />
					{:else}
						<p class="pl-sub">TeX engine unavailable - the view above stands.</p>
					{/if}
				{/if}
				{#if showSolution}
					<div class="statement solution">
						<svelte:boundary>
							<Segments segments={currentQ.solution} bust={figRev} zoomable />
							{#snippet failed()}
								<p class="pl-error" role="alert">Could not display this solution.</p>
							{/snippet}
						</svelte:boundary>
					</div>
					<div class="row">
						<button type="button" class="pl-btn" onclick={() => { showSImage = !showSImage; sImgOk = true; }}>
							{showSImage ? 'Hide compiled image' : 'Render solution as image'}
						</button>
					</div>
					{#if showSImage}
						{#if sImgOk}
							<img class="compiled" src={renderUrl('solution')} alt="Compiled solution" onerror={() => (sImgOk = false)} />
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
						{#key currentQ.paperId + currentQ.number}
							<ClassifyForm
								paperId={paperId}
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
					{#if showFigures}
						<FigurePanel
							paperId={currentQ.paperId}
							qn={currentQ.number}
							rev={figRev}
							onChanged={async () => {
								figRev += 1;
								const all = await api.getQuestions(paperId);
								questions = all;
								currentQ = all.find((q) => q.number === current) ?? currentQ;
							}}
						/>
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
		grid-template-columns: 168px 1fr;
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
		flex-direction: column;
		align-items: flex-start;
		gap: 0;
		text-align: left;
		border: none;
		border-left: 3px solid transparent;
		background: none;
		border-radius: 8px;
		padding: 8px 10px;
		min-height: 44px;
		width: 100%;
	}
	.qbtn:hover {
		background: var(--pl-raised);
	}
	.qbtn.active {
		background: var(--pl-raised);
		border-left-color: var(--pl-seal);
		font-weight: 600;
	}
	.qbtn .pl-mono {
		overflow-wrap: anywhere;
		line-height: 1.35;
	}
	.pane {
		max-width: 1000px;
	}
	.pane h2.qtitle {
		font-family: 'Roboto', Inter, system-ui, sans-serif;
		font-size: 1.75rem;
		font-weight: 600;
		margin: 4px 0 10px;
	}
	.qtitle-row {
		display: flex;
		align-items: center;
		gap: 16px;
	}
	.qtitle-row .qtitle {
		margin-top: 4px;
	}
	.cartslot {
		margin-left: auto;
		display: inline-flex;
		align-items: center;
	}
	.editlink {
		margin-left: 0;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 34px;
		height: 34px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-surface);
		color: var(--pl-ink-soft);
		flex-shrink: 0;
	}
	.editlink:hover {
		color: var(--pl-seal);
		border-color: var(--pl-seal);
	}
	.editlink svg {
		width: 16px;
		height: 16px;
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
	.compiled {
		max-width: 100%;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		margin: 8px 0;
	}
	.row {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		margin: 12px 0 4px;
	}
	.solution {
		border-top: 1px solid var(--pl-line);
		padding-top: 12px;
	}
	.mobtabs {
		display: none;
	}
	@media (max-width: 760px) {
		h1 {
			font-size: 1.4rem;
		}
		.pane h2.qtitle {
			font-size: 1.35rem;
		}
		.mobtabs {
			display: inline-flex;
			gap: 2px;
			background: var(--pl-raised);
			border: 1px solid var(--pl-line);
			border-radius: var(--pl-radius-pill);
			padding: 3px;
			margin: 12px 0 0;
			width: max-content;
			max-width: 100%;
		}
		.mobtabs button {
			border: none;
			background: none;
			border-radius: var(--pl-radius-pill);
			padding: 6px 18px;
			min-height: 0;
			font-size: 0.82rem;
			font-weight: 600;
			color: var(--pl-ink-soft);
			cursor: pointer;
			white-space: nowrap;
		}
		.mobtabs button.active {
			background: var(--pl-surface);
			color: var(--pl-ink);
			box-shadow: var(--pl-shadow-sm);
		}
		.desk {
			grid-template-columns: 1fr;
			margin-top: 12px;
		}
		.desk[data-view='list'] .pane {
			display: none;
		}
		.desk[data-view='question'] .index {
			display: none;
		}
		.index {
			max-height: none;
			overflow: visible;
		}
		.statement {
			font-size: 16px;
		}
	}
</style>
