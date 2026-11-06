<script>
	/**
	 * Live Question Sheet on real A4 pages. Each block loads once (shared
	 * session cache), dresses to generated numbers, and flattens into
	 * paragraph/figure rows so pages fill tightly. Only extremes are kept
	 * together: doc/section/passage headers and each question's first row
	 * never strand alone at a page bottom. Pure function of draft state.
	 */
	import { untrack } from 'svelte';
	import { toRoman } from '$lib/numbering.js';
	import { isParagraphId, parseParagraphRange } from '$lib/paragraph.js';
	import { sectionMeta } from '$lib/sectionMeta.js';
	import { dressQuestion } from '$lib/paperDress.js';
	import { getQuestionDetail, dropQuestionDetail } from '$lib/questionCache.js';
	import { splitTopBlocks } from '$lib/flowsplit.js';
	import { withTimeout } from '$lib/async.js';
	import Segments from '$lib/components/Segments.svelte';
	import PagedSheet from '$lib/components/PagedSheet.svelte';

	let { title = '', ordered = [], numbering, sections = [], mode = 'paper', bare = true } = $props();

	const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

	let details = $state({});
	let rev = $state(0);

	const idsKey = $derived(ordered.map((e) => `${e.blockId}:${e.paperId}:${e.number}`).join(','));

	const paraIndex = $derived.by(() => {
		const m = new Map();
		let i = 0;
		for (const e of ordered) if (isParagraphId(e.number, e.qtype)) m.set(e.blockId, toRoman(++i));
		return m;
	});

	$effect(() => {
		void idsKey;
		void rev;
		let cancelled = false;
		// details reads are untracked: otherwise marking loading:true would
		// retrigger this effect and cancel the in-flight fetches (eternal
		// skeletons). idsKey/rev are the only retriggers.
		const missing = untrack(() =>
			ordered.filter((e) => {
				const k = details[e.blockId];
				const fresh = k && k.loading && Date.now() - (k.at ?? 0) < 25000;
				return !(k && (k.ready || k.missing || fresh));
			})
		);
		if (missing.length === 0) return;
		for (const e of missing) details[e.blockId] = { loading: true, at: Date.now() };
		(async () => {
			await Promise.all(missing.map(async (e) => {
				try {
					const d = await withTimeout(
						getQuestionDetail(e.paperId, e.number), 20000, 'Backend timed out — is it running on port 8000?');
					if (cancelled) return;
					// Store RAW; dressing happens in rows (pure, current numbering).
					details[e.blockId] = { ready: true, data: d.question ?? [] };
				} catch (err) {
					if (cancelled) return;
					const msg = String(err?.message ?? err);
					// Our 20s timeout leaves the shared cached promise pending
					// until the 30s api abort; evict it so Retry fetches fresh.
					if (msg.includes('Backend timed out')) {
						try { dropQuestionDetail(e.paperId, e.number); } catch { /* ignore */ }
					}
					details[e.blockId] = { error: msg };
				}
			}));
		})();
		return () => {
			cancelled = true;
		};
	});

	function retryAll() {
		for (const e of ordered) {
			const k = details[e.blockId];
			if (!k) continue;
			const stale = k.loading && Date.now() - (k.at ?? 0) > 10000;
			if (k.error || stale) {
				try { dropQuestionDetail(e.paperId, e.number); } catch { /* ignore */ }
				delete details[e.blockId];
			}
		}
		rev++;
	}

	const failedIds = $derived(
		ordered.filter((e) => details[e.blockId]?.error).map((e) => e.blockId)
	);
	const failedMsg = $derived(
		failedIds.length > 0 ? details[failedIds[0]]?.error ?? '' : ''
	);

	function reload(bid) {
		const entry = ordered.find((o) => o.blockId === bid);
		if (!entry) return;
		dropQuestionDetail(entry.paperId, entry.number);
		delete details[bid];
		rev++;
	}

	/** Flatten one loaded block into measurable rows. */
	function blockRows(entry) {
		const d = details[entry.blockId];
		if (!d || d.loading)
			return [{ id: `${entry.blockId}:loading`, kind: 'loading' }];
		if (d.error)
			return [{ id: `${entry.blockId}:error`, kind: 'error', entry, message: d.error }];
		const nums = numbering.byBlock[entry.blockId] ?? [];
		const pl = paraIndex.get(entry.blockId);
		const raw = d.data ?? [];
		const para = parseParagraphRange(entry.number, entry.qtype);
		const dressed = dressQuestion(raw, { numbers: nums, para });
		const out = [];
		if (pl) out.push({ id: `${entry.blockId}:para`, kind: 'parahead', label: pl, keepWithNext: true });
		let first = true;
		let n = 0;
		const pushSeg = (seg) => {
			if (seg.kind === 'text' && typeof seg.html === 'string') {
				const parts = splitTopBlocks(seg.html);
				if (parts.length === 0) return;
				for (const piece of parts) {
					out.push({
						id: `${entry.blockId}:t${n++}`,
						kind: 'seg',
						seg: { kind: 'text', html: piece },
						keepWithNext: false
					});
					first = false;
				}
				return;
			}
			out.push({ id: `${entry.blockId}:t${n++}`, kind: 'seg', seg, keepWithNext: false });
			first = false;
		};
		for (const seg of dressed) pushSeg(seg);
		if (nums.length === 0 || out.length === (pl ? 1 : 0)) {
			out.push({
				id: `${entry.blockId}:empty`,
				kind: 'seg',
				seg: { kind: 'text', html: '<p>Nothing rendered for this question.</p>' },
				keepWithNext: false
			});
		}
		void nums;
		return out;
	}

	const rows = $derived.by(() => {
		const out = [{ id: 'doc', kind: 'doc', keepWithNext: true }];
		if (mode === 'assignment') {
			for (const e of ordered) out.push(...blockRows(e));
			return out;
		}
		for (const [si, s] of sections.entries()) {
			const bids = s.blockIds ?? [];
			if (!bids.length) continue;
			out.push({ id: `sec:${s.id}`, kind: 'sec', si, keepWithNext: true });
			for (const bid of bids) {
				const entry = ordered.find((o) => o.blockId === bid);
				if (entry) out.push(...blockRows(entry));
			}
		}
		return out;
	});
</script>

{#if failedIds.length > 0}
	<div class="loadfail" role="alert">
		<strong>Preview can't reach {failedIds.length} of {ordered.length} questions.</strong>
		<span class="pl-sub">{failedMsg}</span>
		<button type="button" class="retry" onclick={retryAll}>Retry failed</button>
	</div>
{/if}
<PagedSheet {rows} row={qrow} />
{#snippet qrow(def)}
	{#if def.kind === 'doc'}
		<header class="dochead">
			<h2>{title?.trim() || 'Untitled paper'}</h2>
			<p class="pl-sub">{mode === 'paper' ? 'Question paper' : 'Assignment'} · {numbering.total} questions</p>
		</header>
	{:else if def.kind === 'sec'}
		{@const s = sections[def.si]}
		{@const secNums = (s.blockIds ?? []).flatMap((bid) => numbering.byBlock[bid] ?? [])}
		{@const meta = sectionMeta(s.atype, secNums.length, (s.blockIds ?? []).length)}
		<div class="sechead">
			<h3>SECTION–{(LETTERS[def.si] ?? `X${def.si + 1}`)}</h3>
			<p class="seckind">({meta.kind})</p>
			<ul>
				{#each meta.lines as line (line)}
					<li>{line}</li>
				{/each}
			</ul>
		</div>
	{:else if def.kind === 'parahead'}
		<p class="parahead">Paragraph {def.label}</p>
	{:else if def.kind === 'loading'}
		<div class="skel" aria-hidden="true"></div>
		<div class="skel short" aria-hidden="true"></div>
	{:else if def.kind === 'error'}
		<p class="pl-error" role="alert">Could not load this question: {def.message}</p>
		<button
			type="button" class="retry"
			onclick={() => reload(def.entry.blockId)}
		>Retry</button>
	{:else}
		<Segments segments={[def.seg]} zoomable eager bare={bare} />
	{/if}
{/snippet}

<style>
	.dochead {
		text-align: center;
		border-bottom: 2px solid #111;
		padding-bottom: 10px;
		margin-bottom: 12px;
	}
	.dochead h2 {
		font-family: var(--pl-font-display);
		font-size: 1.3rem;
		margin: 0 0 2px;
		color: #111;
	}
	.dochead .pl-sub {
		margin: 0;
		color: #5c6066;
	}
	.sechead {
		margin: 2px 0 8px;
		padding-bottom: 8px;
		border-bottom: 1px solid #111;
	}
	.sechead h3 {
		font-family: var(--pl-font-display);
		font-size: 1rem;
		text-align: center;
		margin: 0 0 2px;
		letter-spacing: 0.04em;
		color: #111;
	}
	.seckind {
		text-align: center;
		font-weight: 700;
		font-size: 0.82rem;
		margin: 0 0 8px;
	}
	.sechead ul {
		margin: 0;
		padding-left: 18px;
		font-size: 0.78rem;
		line-height: 1.55;
	}
	.parahead {
		margin: 2px 0 6px;
		font-weight: 700;
		font-size: 0.9rem;
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
	.loadfail {
		border: 1px solid var(--pl-seal);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-seal-soft);
		padding: 10px 12px;
		margin-bottom: 10px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-size: 0.82rem;
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
