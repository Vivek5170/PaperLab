<script>
	/**
	 * Generic A4 pager: lays rows out at fixed 794px, packs them into
	 * 1123px pages (never splitting a row), and scales the whole thing
	 * to fit the column — like a PDF viewer. Print renders 1:1 via
	 * @page A4 margin 0, so screen == export.
	 *
	 * Robustness rules (text cuts must be impossible, not just unlikely):
	 * - Pages NEVER clip: min-height A4, height auto, overflow visible.
	 *   Packing decides page breaks only; a stale/overfull page grows
	 *   visibly instead of cutting text mid-line.
	 * - The frame height comes from the measured flow element itself,
	 *   so the scaled frame can never be shorter than its content.
	 * - Rows are display:flow-root so child margins can't collapse out
	 *   and measured sums match rendered flow exactly.
	 * - First paint stays hidden until the first measure completes, so
	 *   users never see the estimate-based pack (default heights).
	 */
	import { tick, onMount } from 'svelte';
	import { packRows, PAGE_W, PAGE_H, PAD_TOP, PAD_BOTTOM, usableHeight } from '$lib/paginate.js';

	let { rows = [], row, gap = 20 } = $props();

	// A few px of slack so late font/image settling moves breaks early
	// rather than exactly at the edge.
	const MEASURE_SLACK = 12;
	const usableH = usableHeight() - MEASURE_SLACK;
	let heights = $state({});
	let scale = $state(1);
	let viewEl = $state(null);
	let flowEl = $state(null);
	// Exact frame height, measured from the flow itself (unscaled px).
	let flowH = $state(0);
	// First real measure done — gate first paint on this.
	let measuredOnce = $state(false);
	const els = new Map();
	let mtimer = null;
	let ro = null;
	let rowRO = null;
	function ensureRowRO() {
		if (!rowRO) {
			try {
				rowRO = new ResizeObserver(() => schedule());
			} catch {
				rowRO = null;
			}
		}
		return rowRO;
	}

	const pages = $derived.by(() => {
		const items = rows.map((r) => ({
			id: r.id,
			h: heights[r.id] ?? 140,
			keepWithNext: !!r.keepWithNext,
			breakBefore: !!r.breakBefore
		}));
		return packRows(items, usableH);
	});
	// Estimate only (pre-measure fallback); the real frame height comes
	// from flowH once measured.
	const totalHEst = $derived(pages.length * PAGE_H + Math.max(0, pages.length - 1) * gap);
	const frameH = $derived(flowH > 0 ? flowH : totalHEst);

	function track(node, id) {
		els.set(id, node);
		// Per-row observation catches late image/KaTeX/font growth that
		// never resizes an ancestor (pages size to content, but a row's
		// own box always reflects its growth).
		try {
			ensureRowRO()?.observe(node);
		} catch { /* ignore */ }
		schedule();
		return {
			destroy() {
				if (els.get(id) === node) els.delete(id);
				try {
					rowRO?.unobserve(node);
				} catch { /* ignore */ }
			}
		};
	}

	function schedule() {
		clearTimeout(mtimer);
		mtimer = setTimeout(measure, 180);
	}

	async function measure() {
		await tick();
		let changed = false;
		const nh = { ...heights };
		for (const [id, el] of els) {
			if (!el.isConnected) continue;
			const h = Math.ceil(el.offsetHeight);
			if (nh[id] !== h) {
				nh[id] = h;
				changed = true;
			}
		}
		const ids = new Set(rows.map((r) => r.id));
		for (const k of Object.keys(nh)) {
			if (!ids.has(k)) {
				delete nh[k];
				changed = true;
			}
		}
		if (changed) heights = nh;
		if (flowEl) {
			const fh = Math.ceil(flowEl.offsetHeight);
			if (fh > 0 && fh !== flowH) flowH = fh;
		}
		if (!measuredOnce) measuredOnce = true;
	}

	function fit() {
		if (viewEl) scale = Math.min(1, viewEl.clientWidth / PAGE_W);
	}

	$effect(() => {
		rows.map((r) => r.id).join(',');
		schedule();
	});

	// Late image/font growth is the main packing enemy: listen for it
	// directly (capture phase) instead of relying on ResizeObserver alone,
	// plus delayed safety passes for stragglers.
	function onSettled() {
		schedule();
		setTimeout(schedule, 1500);
		setTimeout(schedule, 4000);
	}
	onMount(() => {
		fit();
		ro = new ResizeObserver(() => {
			fit();
			schedule();
		});
		if (viewEl) ro.observe(viewEl);
		if (flowEl) {
			ro.observe(flowEl);
			flowEl.addEventListener('load', schedule, true);
			flowEl.addEventListener('error', schedule, true);
		}
		if (document.fonts?.ready) document.fonts.ready.then(() => schedule()).catch(() => {});
		try {
			document.fonts?.addEventListener?.('loadingdone', schedule);
		} catch { /* older browsers */ }
		onSettled();
		return () => {
			ro?.disconnect();
			try {
				document.fonts?.removeEventListener?.('loadingdone', schedule);
			} catch { /* ignore */ }
			try {
				rowRO?.disconnect();
			} catch { /* ignore */ }
			rowRO = null;
			flowEl?.removeEventListener('load', schedule, true);
			flowEl?.removeEventListener('error', schedule, true);
			clearTimeout(mtimer);
		};
	});
</script>

<div class="pview" bind:this={viewEl}>
	<div
		class="pframe"
		class:pre={!measuredOnce}
		style={`width: ${PAGE_W * scale}px; height: ${Math.ceil(frameH * scale)}px;`}
		aria-busy={!measuredOnce}
	>
		<div class="pscale" bind:this={flowEl} style={`width: ${PAGE_W}px; transform: scale(${scale});`}>
			{#each pages as page, pi (page[0] ?? pi)}
				<div
					class="apage"
					style={`width: ${PAGE_W}px; min-height: ${PAGE_H}px; padding: ${PAD_TOP}px 56px ${PAD_BOTTOM}px; margin-bottom: ${pi < pages.length - 1 ? gap : 0}px;`}
				>
					{#each page as id (id)}
						{@const def = rows.find((r) => r.id === id)}
						{#if def}
							<div class="prow" use:track={id}>{@render row(def)}</div>
						{/if}
					{/each}
				</div>
			{/each}
		</div>
	</div>
</div>

<style>
	.pview {
		width: 100%;
	}
	.pframe {
		margin: 0 auto;
		overflow: hidden;
		position: relative;
	}
	.pframe.pre {
		visibility: hidden;
	}
	.pscale {
		transform-origin: top left;
	}
	.apage {
		position: relative;
		background: #ffffff;
		color: #111111;
		border: 1px solid var(--pl-line);
		border-radius: 2px;
		box-shadow: var(--pl-shadow-md);
		box-sizing: border-box;
		overflow: visible;
		font-size: 0.8125rem;
		line-height: 1.6;
	}
	.prow {
		display: flow-root;
		min-width: 0;
	}
	.apage :global(.fig) {
		margin: 12px 0 14px;
	}
	.apage :global(.fig img) {
		max-width: 250px;
	}
	.apage :global(.pl-table img) {
		max-width: 200px;
	}
	.apage :global(img) {
		max-width: 100%;
		height: auto;
	}
	.apage :global(p) {
		overflow-wrap: anywhere;
	}
	.apage :global(li) {
		overflow-wrap: anywhere;
	}
	/* Measured original-paper rhythm (FITJEE/GTA/ADV): the question number
	   hangs at the body margin, ALL text — stem, wrapped lines, options —
	   aligns at one indent. Markers sit outside; text never double-indents. */
	.apage :global(ol) {
		margin: 0.5em 0;
		padding-left: 2.75em;
	}
	.apage :global(ul) {
		margin: 0.5em 0;
		padding-left: 2.75em;
	}
	.apage :global(p.pl-opt) {
		margin-left: 2.75em;
	}
	@media print {
		.pframe {
			width: auto !important;
			height: auto !important;
			overflow: visible;
		}
		.pframe.pre {
			visibility: visible;
		}
		.pscale {
			transform: none !important;
		}
		.apage {
			box-shadow: none;
			border: none;
			border-radius: 0;
			margin: 0 !important;
		}
		.apage + .apage {
			break-before: page;
		}
	}
	@page {
		size: A4 portrait;
		margin: 0;
	}
</style>
