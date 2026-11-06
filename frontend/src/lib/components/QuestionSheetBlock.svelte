<script>
	/**
	 * One question-sheet entry. Fetches via the shared session cache;
	 * states mirror SolutionBlock. Numbering comes from props only.
	 */
	import { onMount } from 'svelte';
	import { getQuestionDetail, dropQuestionDetail } from '$lib/questionCache.js';
	import { dressQuestion } from '$lib/paperDress.js';
	import { parseParagraphRange } from '$lib/paragraph.js';
	import Segments from '$lib/components/Segments.svelte';

	let { block, numbers = [] } = $props();

	let state = $state('loading'); // loading | ready | missing-q | error
	let segments = $state([]);
	let error = $state('');

	const para = $derived(parseParagraphRange(block.number, block.qtype));
	const shown = $derived(dressQuestion(segments, { numbers, para }));

	const rangeLabel = $derived(
		numbers.length <= 1 ? `Q${numbers[0] ?? '—'}` : `Questions Q${numbers[0]}–Q${numbers[numbers.length - 1]}`
	);

	async function load() {
		state = 'loading';
		error = '';
		try {
			const detail = await getQuestionDetail(block.paperId, block.number);
			segments = detail?.question ?? [];
			state = 'ready';
		} catch (e) {
			const msg = String(e?.message ?? e);
			state = msg.startsWith('404') ? 'missing-q' : 'error';
			error = msg;
		}
	}

	function retry() {
		dropQuestionDetail(block.paperId, block.number);
		load();
	}

	onMount(load);
</script>

<div class="q">
	<p class="qhead"><span class="qn">{rangeLabel}</span></p>
	{#if state === 'loading'}
		<div class="skel" aria-hidden="true"></div>
		<div class="skel short" aria-hidden="true"></div>
	{:else if state === 'ready'}
		<Segments segments={shown} zoomable />
	{:else if state === 'missing-q'}
		<p class="pl-sub">Source question no longer exists (Paper {block.paperId} · Q{block.number}). The number stays reserved in the key.</p>
	{:else}
		<p class="pl-error" role="alert">Could not load this question: {error}</p>
		<button type="button" class="retry" onclick={retry}>Retry</button>
	{/if}
</div>

<style>
	.q {
		margin: 0 0 16px;
		font-size: 0.875rem;
		line-height: 1.65;
	}
	.qhead {
		margin: 0 0 6px;
	}
	.qn {
		font-weight: 700;
		font-size: 0.92rem;
	}
	.skel {
		height: 1em;
		border-radius: 4px;
		background: var(--pl-raised);
		margin: 0.9em 0;
	}
	.skel.short {
		width: 55%;
	}
	.retry {
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		background: none;
		padding: 4px 12px;
		min-height: 32px;
		font-size: 0.8rem;
		font-weight: 600;
		cursor: pointer;
	}
	.retry:hover {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
</style>
