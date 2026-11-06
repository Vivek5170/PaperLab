<script>
	/**
	 * Live Answer Sheet on real A4 pages: key page first (Q.No + Key,
	 * auto-filled from filed answers, manual overrides win), then
	 * detailed solutions flattened into flow rows. Same generated
	 * numbers as the Question Sheet. Pure render of shared state.
	 */
	import { numberLabel } from '$lib/numbering.js';
	import { parseParagraphRange } from '$lib/paragraph.js';
	import {
		dressSolution, isMissingSolutionText, extractAnswerKeys
	} from '$lib/paperDress.js';
	import { getQuestionDetail, dropQuestionDetail } from '$lib/questionCache.js';
	import { splitTopBlocks } from '$lib/flowsplit.js';
	import { builder } from '$lib/builder.js';
	import Segments from '$lib/components/Segments.svelte';
	import KeyTable from '$lib/components/KeyTable.svelte';
	import PagedSheet from '$lib/components/PagedSheet.svelte';

	let { title = '', numbering, blocks = {}, overrides = {}, parsed = {}, ordered = [], onOverride } = $props();

	let details = $state({});
	let rev = $state(0);

	const idsKey = $derived(ordered.map((e) => e.blockId).join(','));

	$effect(() => {
		void idsKey;
		void rev;
		let cancelled = false;
		(async () => {
			for (const e of ordered) {
				if (cancelled) continue;
				const known = details[e.blockId];
				if (known && (known.ready || known.loading || known.missing)) continue;
				details[e.blockId] = { loading: true };
				try {
					const d = await getQuestionDetail(e.paperId, e.number);
					if (cancelled) return;
					const nums = numbering.byBlock[e.blockId] ?? [];
					const sol = d.solution ?? [];
					if (isMissingSolutionText(sol)) {
						details[e.blockId] = { missing: true };
					} else {
						builder.setParsedKeys(e.blockId, extractAnswerKeys(sol));
						details[e.blockId] = {
							ready: true,
							segs: dressSolution(sol, { numbers: nums })
						};
					}
				} catch (err) {
					if (!cancelled) details[e.blockId] = { error: String(err?.message ?? err) };
				}
			}
		})();
		return () => {
			cancelled = true;
		};
	});

	function reload(bid) {
		const entry = ordered.find((o) => o.blockId === bid);
		if (!entry) return;
		dropQuestionDetail(entry.paperId, entry.number);
		delete details[bid];
		rev++;
	}

	/** Flatten one solution block: heading row + flow rows + anchors. */
	function blockRows(entry) {
		const d = details[entry.blockId];
		if (!d || d.loading)
			return [{ id: `${entry.blockId}:loading`, kind: 'loading' }];
		if (d.error)
			return [{ id: `${entry.blockId}:error`, kind: 'error', entry, message: d.error }];
		const nums = numbering.byBlock[entry.blockId] ?? [];
		const out = [{
			id: `${entry.blockId}:solhead`,
			kind: 'solhead',
			label: nums.length <= 1 ? `Solution Q${nums[0] ?? '—'}` : `Solutions Q${nums[0]}–Q${nums[nums.length - 1]}`,
			keepWithNext: true
		}];
		if (d.missing) {
			out.push({ id: `${entry.blockId}:nosol`, kind: 'nosol' });
			return out;
		}
		let n = 0;
		for (const seg of d.segs) {
			if (seg.kind === 'text' && typeof seg.html === 'string') {
				const parts = splitTopBlocks(seg.html);
				if (parts.length === 0) continue;
				for (const piece of parts) {
					out.push({ id: `${entry.blockId}:s${n++}`, kind: 'seg', seg: { kind: 'text', html: piece } });
				}
				continue;
			}
			out.push({ id: `${entry.blockId}:s${n++}`, kind: 'seg', seg });
		}
		if (nums.length > 1) out.push({ id: `${entry.blockId}:anchors`, kind: 'anchors', nums });
		return out;
	}

	const rows = $derived.by(() => {
		const out = [
			{ id: 'doc', kind: 'doc' },
			{ id: 'key', kind: 'key' }
		];
		if (ordered.length > 0) out.push({ id: 'solshead', kind: 'solshead', keepWithNext: true, breakBefore: true });
		for (const e of ordered) out.push(...blockRows(e));
		return out;
	});
</script>

<PagedSheet {rows} row={arow} />
{#snippet arow(def)}
	{#if def.kind === 'doc'}
		<header class="dochead">
			<h2>{title?.trim() || 'Untitled paper'} — Answer key</h2>
		</header>
	{:else if def.kind === 'key'}
		<KeyTable {numbering} {blocks} {overrides} {parsed} {onOverride} />
	{:else if def.kind === 'solshead'}
		<h3 class="solshead">Detailed solutions</h3>
	{:else if def.kind === 'solhead'}
		<h4 class="solhead">{def.label}</h4>
	{:else if def.kind === 'nosol'}
		<p class="pl-sub">No solution on file for this question — the key row above still stands.</p>
	{:else if def.kind === 'loading'}
		<div class="skel" aria-hidden="true"></div>
		<div class="skel short" aria-hidden="true"></div>
	{:else if def.kind === 'error'}
		<p class="pl-error" role="alert">Could not load this solution: {def.message}</p>
		<button
			type="button" class="retry"
			onclick={() => reload(def.entry.blockId)}
		>Retry</button>
	{:else if def.kind === 'anchors'}
		<ul class="anchors" aria-label={`Sub-solutions for ${def.nums.map((n) => `Q${n}`).join(', ')}`}>
			{#each def.nums as n (n)}
				<li><span class="anch">Q{n}</span></li>
			{/each}
		</ul>
	{:else}
		<Segments segments={[def.seg]} zoomable />
	{/if}
{/snippet}

<style>
	.dochead {
		text-align: center;
		border-bottom: 2px solid #111;
		padding-bottom: 10px;
		margin-bottom: 10px;
	}
	.dochead h2 {
		font-family: var(--pl-font-display);
		font-size: 1.25rem;
		margin: 0;
		color: #111;
	}
	.solshead {
		font-family: var(--pl-font-display);
		font-size: 1.15rem;
		margin: 0 0 8px;
		color: #111;
	}
	.solhead {
		font-size: 0.92rem;
		margin: 2px 0 6px;
	}
	.anchors {
		list-style: none;
		margin: 4px 0 8px;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.anch {
		font-weight: 700;
		font-size: 0.8rem;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		padding: 1px 8px;
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
