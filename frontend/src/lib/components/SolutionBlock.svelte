<script>
	/**
	 * One block's solution. Own fetch state machine:
	 * loading → ready | missing-question | missing-solution | error+retry.
	 * Missing solutions/questions NEVER remove the block from numbering
	 * or the key — the heading (with generated numbers) always renders.
	 */
	import { onMount } from 'svelte';
	import { getQuestionDetail, dropQuestionDetail } from '$lib/questionCache.js';
	import Segments from '$lib/components/Segments.svelte';

	let { block, numbers = [] } = $props();

	let state = $state('loading'); // loading | ready | missing-q | missing-sol | error
	let segments = $state([]);
	let error = $state('');

	function solutionMissing(segs) {
		let text = '';
		for (const s of segs ?? []) {
			if (s?.kind === 'text' && typeof s.html === 'string')
				text += s.html.replace(/<[^>]*>/g, ' ');
		}
		return text.replace(/\s+/g, ' ').trim() === '*missing*';
	}

	function heading() {
		if (numbers.length <= 1) return `Solution Q${numbers[0] ?? '—'}`;
		return `Solutions Q${numbers[0]}–Q${numbers[numbers.length - 1]}`;
	}

	async function load() {
		state = 'loading';
		error = '';
		try {
			const detail = await getQuestionDetail(block.paperId, block.number);
			const sol = detail?.solution ?? [];
			if (solutionMissing(sol)) state = 'missing-sol';
			else {
				segments = sol;
				state = 'ready';
			}
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

<section class="sol" aria-label={heading()}>
	<h4>{heading()} <span class="src">· Paper {block.paperId} · Q{block.number}</span></h4>
	{#if state === 'loading'}
		<div class="skel" aria-hidden="true"></div>
		<div class="skel short" aria-hidden="true"></div>
	{:else if state === 'ready'}
		<Segments {segments} zoomable />
	{:else if state === 'missing-sol'}
		<p class="pl-sub">No solution on file for this question — the key row above still stands.</p>
	{:else if state === 'missing-q'}
		<p class="pl-sub">Source question no longer exists (Paper {block.paperId} · Q{block.number}). Remove this block or re-import it.</p>
	{:else}
		<p class="pl-error" role="alert">Could not load this solution: {error}</p>
		<button type="button" class="pl-btn" onclick={retry}>Retry</button>
	{/if}
</section>

<style>
	.sol {
		border-top: 1px solid var(--pl-line);
		padding: 12px 0 4px;
	}
	.sol h4 {
		margin: 0 0 8px;
		font-size: 1rem;
	}
	.src {
		font-weight: 400;
		font-size: 0.78rem;
		color: var(--pl-ink-soft);
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
	.pl-btn {
		margin-top: 8px;
	}
</style>
