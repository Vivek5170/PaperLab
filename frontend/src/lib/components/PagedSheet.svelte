<script>
	/**
	 * Generic A4 pager: lays rows out at fixed 794px, packs them into
	 * 1123px pages (never splitting a row), and scales the whole thing
	 * to fit the column — like a PDF viewer. Print renders 1:1 via
	 * @page A4 margin 0, so screen == export.
	 *
	 * Rows remount only when their page assignment actually changes;
	 * typing inside a row re-measures without remounting.
	 */
	import { tick, onMount } from 'svelte';
	import { packRows, PAGE_W, PAGE_H, PAD_TOP, PAD_BOTTOM, usableHeight } from '$lib/paginate.js';

	let { rows = [], row, gap = 20 } = $props();

	// A few px of slack so late font/image settling never clips content.
	const MEASURE_SLACK = 12;
	const usableH = usableHeight() - MEASURE_SLACK;
	let heights = $state({});
	let scale = $state(1);
	let viewEl = $state(null);
	let flowEl = $state(null);
	const els = new Map();
	let mtimer = null;
	let ro = null;

	const pages = $derived.by(() => {
		const items = rows.map((r) => ({
			id: r.id,
			h: heights[r.id] ?? 280,
			header: !!r.header,
			breakBefore: !!r.breakBefore
		}));
		return packRows(items, usableH);
	});
	const totalH = $derived.by(() => {
		let t = 0;
		pages.forEach((pg, pi) => {
			t += tallPages.has(pi) ? PAD_TOP + (heights[pg[0]] ?? 0) + PAD_BOTTOM : PAGE_H;
			if (pi < pages.length - 1) t += gap;
		});
		return t;
	});
	// A lone row taller than one page gets a growing page (never clipped).
	const tallPages = $derived.by(() => {
		const s = new Set();
		pages.forEach((pg, pi) => {
			if (pg.length === 1 && (heights[pg[0]] ?? 0) > usableH) s.add(pi);
		});
		return s;
	});

	function track(node, id) {
		els.set(id, node);
		schedule();
		return {
			destroy() {
				if (els.get(id) === node) els.delete(id);
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
		onSettled();
		return () => {
			ro?.disconnect();
			flowEl?.removeEventListener('load', schedule, true);
			flowEl?.removeEventListener('error', schedule, true);
			clearTimeout(mtimer);
		};
	});
</script>

<div class="pview" bind:this={viewEl}>
	<div class="pframe" style={`width: ${PAGE_W * scale}px; height: ${totalH * scale}px;`}>
		<div class="pscale" bind:this={flowEl} style={`width: ${PAGE_W}px; transform: scale(${scale});`}>
			{#each pages as page, pi (pi)}
				<div
					class="apage"
					class:tall={tallPages.has(pi)}
					style={`width: ${PAGE_W}px; ${tallPages.has(pi) ? `min-height: ${PAGE_H}px;` : `height: ${PAGE_H}px;`} padding: ${PAD_TOP}px 56px ${PAD_BOTTOM}px; margin-bottom: ${pi < pages.length - 1 ? gap : 0}px;`}
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
		overflow: hidden;
		font-size: 0.8125rem;
		line-height: 1.6;
	}
	.apage.tall {
		overflow: visible;
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
	@media print {
		.pframe {
			width: auto !important;
			height: auto !important;
			overflow: visible;
		}
		.pscale {
			transform: none !important;
		}
		.apage {
			box-shadow: none;
			border: none;
			border-radius: 0;
			margin: 0;
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
