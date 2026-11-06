<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	import StatCard from '$lib/components/StatCard.svelte';
	import SegmentedTabs from '$lib/components/SegmentedTabs.svelte';

	const isArchivist = $derived($role === 'archivist');

	let stats = $state(null);
	let loading = $state(true);
	let error = $state('');
	let currency = $state('INR');
	let rate = $state(95);
	let configOpen = $state(false);
	let papers = $state([]);
	let victimId = $state('');
	let confirmDelete = $state(false);
	let deleting = $state(false);
	let dangerMsg = $state('');
	let disk = $state(null);
	let armRender = $state(false);
	let armInter = $state(false);
	let purging = $state('');
	let purgeMsg = $state('');
	let pdfs = $state(null);
	let selPaths = $state([]);
	let selUnlinked = $state([]);
	let armPdfDel = $state(false);
	let deletingPdfs = $state(false);
	let pdfMsg = $state('');

	const currencyTabs = [
		{ id: 'USD', label: 'USD ($)' },
		{ id: 'INR', label: 'INR (Rs.)' }
	];

	const sym = $derived(currency === 'INR' ? '₹' : '$');
	const convert = (usd) => (currency === 'INR' ? usd * rate : usd);
	const money = (usd, digits = 2) => `${sym}${convert(usd).toFixed(digits)}`;

	async function load() {
		loading = true;
		error = '';
		try {
			const [s, p, d, pdf] = await Promise.all([
				api.getStats(),
				api.listPapers(),
				api.getDiskUsage(),
				api.getPaperPdfs()
			]);
			stats = s;
			papers = p;
			disk = d;
			pdfs = pdf;
			currency = String(stats.currencyDefault || 'INR')
				.toLowerCase()
				.startsWith('in')
				? 'INR'
				: 'USD';
			rate = Number(stats.usdToInr) || 95;
			victimId = String(papers[0]?.id ?? '');
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	async function deleteVictim() {
		if (!victimId || !confirmDelete) return;
		deleting = true;
		dangerMsg = '';
		try {
			await api.deletePaper(Number(victimId));
			dangerMsg = `Deleted paper ${victimId}.`;
			confirmDelete = false;
			await load();
		} catch (e) {
			dangerMsg = `Delete failed: ${e.message}`;
		} finally {
			deleting = false;
		}
	}

	function onKeydown(event) {
		if (event.key === 'Escape') configOpen = false;
	}

	function fmtBytes(n) {
		if (n == null) return '–';
		if (n >= 1048576) return `${(n / 1048576).toFixed(1)} MB`;
		if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
		return `${n} B`;
	}

	async function purge(kind) {
		const armed = kind === 'render' ? armRender : armInter;
		if (!armed) {
			if (kind === 'render') {
				armRender = true;
				armInter = false;
			} else {
				armInter = true;
				armRender = false;
			}
			return;
		}
		armRender = false;
		armInter = false;
		purging = kind;
		purgeMsg = '';
		try {
			const res =
				kind === 'render' ? await api.purgeRenderCache() : await api.purgeIntermediates();
			const extra =
				res.cleaned != null || res.crop != null
					? ` (${res.cleaned ?? 0} cleaned + ${res.crop ?? 0} crop)`
					: '';
			purgeMsg = `Deleted ${res.deleted} file${res.deleted === 1 ? '' : 's'}${extra}, freed ${fmtBytes(res.bytes)}.`;
			disk = await api.getDiskUsage();
		} catch (e) {
			purgeMsg = `Delete failed: ${e.message}`;
		} finally {
			purging = '';
		}
	}

	const selCount = $derived(selPaths.length + selUnlinked.length);

	async function deleteSelectedPdfs() {
		if (selCount === 0 || purging !== '' || deletingPdfs) return;
		if (!armPdfDel) {
			armPdfDel = true;
			return;
		}
		armPdfDel = false;
		deletingPdfs = true;
		pdfMsg = '';
		try {
			const res = await api.deletePaperPdfs({
				paths: selPaths,
				unlinked: selUnlinked.map((k) => {
					const i = k.indexOf(':');
					return { location: k.slice(0, i), name: k.slice(i + 1) };
				})
			});
			const bits = [`Deleted ${res.deleted} file${res.deleted === 1 ? '' : 's'}`];
			if ((res.cleared ?? []).length) bits.push(`cleared ${res.cleared.length} paper reference${res.cleared.length === 1 ? '' : 's'}`);
			if ((res.missing ?? []).length) bits.push(`${res.missing.length} already missing`);
			if ((res.refused ?? []).length) bits.push(`${res.refused.length} refused (outside data/)`);
			bits.push(`freed ${fmtBytes(res.bytes)}`);
			pdfMsg = bits.join(' · ') + '.';
			selPaths = [];
			selUnlinked = [];
			const [d, pdf] = await Promise.all([api.getDiskUsage(), api.getPaperPdfs()]);
			disk = d;
			pdfs = pdf;
		} catch (e) {
			pdfMsg = `Delete failed: ${e.message}`;
		} finally {
			deletingPdfs = false;
		}
	}

	onMount(async () => {
		if (!isArchivist) {
			loading = false;
			return;
		}
		await load();
	});
</script>

<svelte:head><title>Usage Ledger - PaperLab</title></svelte:head>
<svelte:window onkeydown={onKeydown} />

<div class="ledger-head">
	<div>
		<h1>Usage Ledger</h1>
		<p class="pl-sub">Token accounting and cost. Student views stay clean.</p>
	</div>
	{#if isArchivist && stats}
		<div class="config-wrap">
			<button
				type="button"
				class="pl-btn config-btn"
				aria-haspopup="dialog"
				aria-expanded={configOpen}
				onclick={() => (configOpen = !configOpen)}
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
					<circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5h.1a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1z" />
				</svg>
				Config
			</button>
			{#if configOpen}
				<div class="scrim" onclick={() => (configOpen = false)} aria-hidden="true"></div>
				<div class="popover" role="dialog" aria-label="Display settings">
					<p class="pop-title">Currency</p>
					<SegmentedTabs tabs={currencyTabs} bind:value={currency} />
					{#if currency === 'INR'}
						<label class="rate">
							USD to INR rate
							<input
								type="number"
								min="1"
								step="0.5"
								bind:value={rate}
								aria-label="USD to INR rate, display only"
							/>
						</label>
					{/if}
					<dl class="pricing">
						<div><dt>Input</dt><dd>$0.10 /Mtok</dd></div>
						<div><dt>Cached input</dt><dd>$0.002 /Mtok</dd></div>
						<div><dt>Output</dt><dd>$0.20 /Mtok</dd></div>
						{#if currency === 'INR'}
							<div><dt>Exchange rate</dt><dd>1 USD = ₹{rate}</dd></div>
						{/if}
					</dl>
				</div>
			{/if}
		</div>
	{/if}
</div>

{#if !isArchivist}
	<div class="pl-card">
		<p>This area needs archivist access. Use the role switch in the sidebar to log in.</p>
	</div>
{:else}
	<button type="button" class="pl-btn" onclick={load}>Refresh metrics</button>

	{#if loading}
		<p class="pl-sub">Loading stats…</p>
	{:else if error}
		<div class="pl-error" role="alert">
			<strong>Could not load stats.</strong>
			<p class="pl-mono">{error}</p>
		</div>
	{:else if stats}
		<div class="stats">
			<StatCard label="Total cost" value={money(stats.totalCost)} />
			<StatCard label="Extraction" value={money(stats.extraction)} />
			<StatCard label="Tagging" value={money(stats.tagging)} />
			<StatCard label="Turns" value={stats.turns.toLocaleString('en-US')} />
		</div>

		<div class="pl-table-wrap">
			<table class="pl-table">
				<thead>
					<tr>
						<th>paper</th><th>status</th><th>turns</th><th>input</th>
						<th>cached</th><th>output</th><th>reasoning</th><th>wall</th>
						<th>extraction ({sym})</th><th>tagging ({sym})</th><th>total ({sym})</th>
					</tr>
				</thead>
				<tbody>
					{#each stats.rows ?? [] as row (row.paper)}
						<tr>
							<td>{row.paper}</td>
							<td>{row.status}</td>
							<td class="pl-mono num">{row.turns}</td>
							<td class="pl-mono num">{row.input}</td>
							<td class="pl-mono num">{row.cached}</td>
							<td class="pl-mono num">{row.output}</td>
							<td class="pl-mono num">{row.reasoning}</td>
							<td class="pl-mono">{row.wall}</td>
							<td class="pl-mono num">{convert(row.extraction).toFixed(4)}</td>
							<td class="pl-mono num">{convert(row.tagging).toFixed(4)}</td>
							<td class="pl-mono num">{convert(row.total).toFixed(4)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		{#if (stats.errors ?? []).length}
			{#each stats.errors as item (item.paper)}
				<div class="pl-error" role="alert">#{item.paper}: {item.error}</div>
			{/each}
		{/if}

		<h3 class="section-title">Breakdown by phase (indexer / extractor / topics)</h3>
		<div class="pl-table-wrap">
			<table class="pl-table">
				<thead>
					<tr>
						<th>phase</th><th>turns</th><th>fresh</th>
						<th>cached</th><th>output</th><th>cost ({sym})</th>
					</tr>
				</thead>
				<tbody>
					{#each stats.phases ?? [] as ph (ph.phase)}
						<tr>
							<td>{ph.phase}</td>
							<td class="pl-mono num">{ph.turns}</td>
							<td class="pl-mono num">{ph.fresh}</td>
							<td class="pl-mono num">{ph.cached}</td>
							<td class="pl-mono num">{ph.output}</td>
							<td class="pl-mono num">{convert(ph.cost).toFixed(4)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<h3 class="section-title">Reclaimable disk</h3>
		<div class="reclaim">
			<div class="pl-card">
				<p class="rk-title">Render cache</p>
				<p class="rk-size">{disk ? fmtBytes(disk.renderCache.bytes) : '–'}</p>
				<p class="pl-sub rk-note">
					{disk ? `${disk.renderCache.files} compiled figure${disk.renderCache.files === 1 ? '' : 's'}` : '…'}.
					Regenerates on the next Render click. Safe to delete any time.
				</p>
				<button
					type="button"
					class="pl-btn"
					disabled={purging !== '' || !disk?.renderCache.files}
					onclick={() => purge('render')}
				>
					{purging === 'render' ? 'Deleting…' : armRender ? 'Click again to confirm' : 'Delete render cache'}
				</button>
			</div>
			<div class="pl-card">
				<p class="rk-title">Crop + cleaned PDFs</p>
				<p class="rk-size">
					{disk ? fmtBytes((disk.cropPdfs?.bytes ?? 0) + (disk.cleanedPdfs.bytes ?? 0)) : '–'}
				</p>
				<p class="pl-sub rk-note">
					{disk
						? `${disk.cropPdfs?.files ?? 0} crop + ${disk.cleanedPdfs.files} cleaned intermediate file${(disk.cropPdfs?.files ?? 0) + disk.cleanedPdfs.files === 1 ? '' : 's'}`
						: '…'}
					{disk && (disk.cleanedPdfs.protected || disk.cropPdfs?.protected)
						? ` · ${(disk.cleanedPdfs.protected ?? 0) + (disk.cropPdfs?.protected ?? 0)} DB-referenced kept`
						: ''}.
					Crop canvases rebuild from cleaned PDFs; cleaned rebuilds from the question PDF on the next run.
				</p>
				<button
					type="button"
					class="pl-btn"
					disabled={purging !== '' || !((disk?.cropPdfs?.files ?? 0) + (disk?.cleanedPdfs?.files ?? 0))}
					onclick={() => purge('inter')}
				>
					{purging === 'inter' ? 'Deleting…' : armInter ? 'Click again to confirm' : 'Delete crop + cleaned'}
				</button>
			</div>
		</div>
		{#if purgeMsg}<p class="pl-sub" role="status">{purgeMsg}</p>{/if}

		<h3 class="section-title">Paper PDFs</h3>
		<p class="pl-sub pdf-lead">
			Tick QP / solution PDFs to delete. Deleting a paper's file also clears its reference —
			the reader will show no PDF for it. Crop canvases are handled by the purge above.
		</p>
		{#if pdfs}
			<div class="pdfpick">
				<ul class="pdfpick-list" role="listbox" aria-label="Paper PDFs to delete" aria-multiselectable="true">
					{#each pdfs.papers as g (g.id)}
						{@const live = g.files.filter((f) => f.exists)}
						{@const all = [...new Set(live.flatMap((f) => f.storedAll ?? [f.stored]))]}
						{@const on = all.length > 0 && all.every((s) => selPaths.includes(s))}
						{#if live.length}
							<li class="pdfgrp">
								<button
									type="button"
									role="option"
									aria-selected={on}
									class="pdfgrp-btn"
									class:on={on}
									disabled={purging !== '' || deletingPdfs}
									title={all.join(' + ')}
									onclick={() => {
										selPaths = on
											? selPaths.filter((x) => !all.includes(x))
											: [...new Set([...selPaths, ...all])];
									}}
								>
									<span class="tick" aria-hidden="true">{#if on}✓{/if}</span>
									<span class="pdfgrp-name">#{g.id} {g.name}</span>
									<span class="opt-count">{live.length} file{live.length === 1 ? '' : 's'} · {fmtBytes(live.reduce((a, f) => a + (f.bytes ?? 0), 0))}</span>
								</button>
							</li>
						{/if}
					{/each}
					{#if (pdfs.unlinked ?? []).length}
						<li class="pdfgrp" aria-hidden="true">Unlinked PDFs</li>
						{#each pdfs.unlinked as u (`${u.location}:${u.name}`)}
							{@const key = `${u.location}:${u.name}`}
							<li>
								<button
									type="button"
									role="option"
									aria-selected={selUnlinked.includes(key)}
									class="pdfrow"
									class:on={selUnlinked.includes(key)}
									disabled={purging !== '' || deletingPdfs}
									title={`${u.location}/${u.name}`}
									onclick={() => {
										selUnlinked = selUnlinked.includes(key)
											? selUnlinked.filter((x) => x !== key)
											: [...selUnlinked, key];
									}}
								>
									<span class="tick" aria-hidden="true">{#if selUnlinked.includes(key)}✓{/if}</span>
									<span class="kind">{u.location}</span>
									<span class="pdfname pl-mono">{u.name}</span>
									<span class="opt-count">{fmtBytes(u.bytes)}</span>
								</button>
							</li>
						{/each}
					{/if}
				</ul>
				<div class="pdfpick-foot">
					<span class="footbtns">
						<button
							type="button"
							class="pdf-clear"
							onclick={() => {
								selPaths = [
									...new Set(
										pdfs.papers.flatMap((g) =>
											g.files.filter((f) => f.exists).flatMap((f) => f.storedAll ?? [f.stored])
										)
									)
								];
								selUnlinked = (pdfs.unlinked ?? []).map((u) => `${u.location}:${u.name}`);
							}}
						>
							Select all
						</button>
						<button
							type="button"
							class="pdf-clear"
							disabled={selCount === 0}
							onclick={() => {
								selPaths = [];
								selUnlinked = [];
							}}
						>
							Clear
						</button>
					</span>
					<span class="pl-sub">{selCount ? `${selCount} selected` : 'No files selected'}</span>
				</div>
			</div>
			<div class="row pdfdel">
				<button
					type="button"
					class="pl-btn pl-btn-danger"
					disabled={selCount === 0 || purging !== '' || deletingPdfs}
					onclick={deleteSelectedPdfs}
				>
					{deletingPdfs ? 'Deleting…' : armPdfDel ? `Click again to delete ${selCount}` : `Delete selected${selCount ? ` (${selCount})` : ''}`}
				</button>
				{#if pdfMsg}<span class="pl-sub" role="status">{pdfMsg}</span>{/if}
			</div>
		{/if}

		<details class="danger">
			<summary>Danger zone: delete a paper</summary>			<div class="danger-body">
				<p class="pl-sub">Removes the DB row, its questions + token rows, its Outputs folder, and its managed source PDFs (data tree). Files outside data/ are never touched.</p>
				<p class="field-label" id="victim-label">Paper to delete</p>
				<div class="victim-list" role="radiogroup" aria-labelledby="victim-label">
					{#each papers as p (p.id)}
						<label class="victim">
							<input
								type="radio"
								name="victim"
								value={String(p.id)}
								bind:group={victimId}
							/>
							<span class="victim-text">#{p.id} - {p.title} [{p.status}]</span>
						</label>
					{/each}
				</div>
				<label class="inline">
					<input type="checkbox" bind:checked={confirmDelete} />
					I understand #{victimId} and its outputs will be deleted
				</label>
				<div class="row">
					<button
						type="button"
						class="pl-btn pl-btn-danger"
						disabled={!confirmDelete || !victimId || deleting}
						onclick={deleteVictim}
					>
						{deleting ? 'Deleting…' : 'Delete paper'}
					</button>
					{#if dangerMsg}<span class="pl-sub" role="status">{dangerMsg}</span>{/if}
				</div>
			</div>
		</details>
	{/if}
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.ledger-head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
	}
	.config-wrap {
		position: relative;
		flex-shrink: 0;
	}
	.config-btn svg {
		width: 18px;
		height: 18px;
	}
	.scrim {
		position: fixed;
		inset: 0;
		z-index: 40;
	}
	.popover {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		z-index: 41;
		width: 260px;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		box-shadow: var(--pl-shadow-md);
		padding: 16px;
	}
	.pop-title {
		font-weight: 600;
		font-size: 0.85rem;
		margin: 0 0 8px;
	}
	.rate {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-weight: 600;
		font-size: 0.85rem;
		margin-top: 12px;
	}
	.pricing {
		margin: 12px 0 0;
		border-top: 1px solid var(--pl-line);
		padding: 12px 0 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.pricing div {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		font-size: 0.85rem;
		margin: 0;
	}
	.pricing dt {
		color: var(--pl-ink-soft);
	}
	.pricing dd {
		margin: 0;
		font-family: var(--pl-font-mono);
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 12px;
		margin: 20px 0 8px;
	}
	.num {
		text-align: right;
	}
	.section-title {
		font-size: 1rem;
		margin: 24px 0 8px;
	}
	.reclaim {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
	}
	.rk-title {
		font-weight: 600;
		margin: 0;
	}
	.rk-size {
		font-family: var(--pl-font-mono);
		font-size: 1.4rem;
		margin: 4px 0;
	}
	.rk-note {
		font-size: 0.82rem;
		margin: 0 0 12px;
	}
	.pdf-lead {
		margin: -4px 0 12px;
	}
	.pdfpick {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		background: var(--pl-surface);
		display: flex;
		flex-direction: column;
		margin-bottom: 12px;
	}
	.pdfpick-list {
		list-style: none;
		margin: 0;
		padding: 6px;
		overflow-y: auto;
		min-height: 0;
		max-height: 320px;
	}
	.pdfgrp {
		position: sticky;
		top: -6px;
		background: var(--pl-surface);
		z-index: 1;
		border-bottom: 1px solid var(--pl-line);
	}
	.pdfgrp-btn {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		border: none;
		background: none;
		padding: 8px 10px 6px;
		font-size: 0.78rem;
		font-weight: 700;
		text-align: left;
		cursor: pointer;
		color: var(--pl-ink);
		border-radius: var(--pl-radius-sm);
	}
	.pdfgrp-btn:hover:not(:disabled) {
		background: var(--pl-raised);
	}
	.pdfgrp-btn:disabled {
		cursor: default;
	}
	.pdfgrp-btn .tick {
		width: 20px;
		height: 20px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		font-size: 0.8rem;
		font-weight: 400;
		color: #fff;
	}
	.pdfgrp-btn.on .tick {
		background: var(--pl-seal);
		border-color: var(--pl-seal);
	}
	.pdfgrp-name {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.pdfgrp-btn .opt-count {
		color: var(--pl-ink-soft);
		font-size: 0.75rem;
		font-weight: 400;
		flex-shrink: 0;
	}
	.pdfrow {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		border: none;
		background: none;
		padding: 8px 10px;
		border-radius: var(--pl-radius-sm);
		font-size: 0.85rem;
		text-align: left;
		cursor: pointer;
		color: var(--pl-ink);
	}
	.pdfrow:hover:not(:disabled) {
		background: var(--pl-raised);
	}
	.pdfrow:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.pdfrow.static {
		cursor: default;
	}
	.pdfrow.static:hover {
		background: none;
	}
	.pdfrow .tick {
		width: 20px;
		height: 20px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		font-size: 0.8rem;
		color: #fff;
	}
	.pdfrow.on .tick {
		background: var(--pl-seal);
		border-color: var(--pl-seal);
	}
	.pdfrow .kind {
		font-size: 0.7rem;
		font-weight: 700;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		padding: 1px 7px;
		flex-shrink: 0;
	}
	.pdfname {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.pdfrow .opt-count {
		color: var(--pl-ink-soft);
		font-size: 0.75rem;
		flex-shrink: 0;
	}
	.pdfpick-foot {
		border-top: 1px solid var(--pl-line);
		padding: 4px 6px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.footbtns {
		display: inline-flex;
		align-items: center;
		gap: 2px;
	}
	.pdf-clear {
		border: none;
		background: none;
		color: var(--pl-seal);
		font-weight: 600;
		font-size: 0.82rem;
		padding: 8px 10px;
		min-height: 0;
		cursor: pointer;
	}
	.pdf-clear:disabled {
		color: var(--pl-ink-soft);
		opacity: 0.5;
		cursor: default;
	}
	.pdfdel {
		margin-top: 4px;
	}
	.danger {
		margin-top: 24px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		background: var(--pl-surface);
	}
	.danger summary {
		cursor: pointer;
		font-weight: 600;
		min-height: 44px;
		display: inline-flex;
		align-items: center;
		padding: 0 16px;
	}
	.danger-body {
		border-top: 1px solid var(--pl-line);
		padding: 16px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.danger-body label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-weight: 600;
		font-size: 0.85rem;
	}
	.danger-body .inline {
		flex-direction: row;
		align-items: center;
		font-weight: 500;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.pl-btn-danger {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.pl-btn-danger:hover:not(:disabled) {
		background: var(--pl-seal);
		color: #fff;
	}
	.pl-btn:disabled {
		opacity: 1;
		cursor: not-allowed;
		background: var(--pl-raised);
		color: var(--pl-ink-soft);
		border-color: var(--pl-line);
	}
	.field-label {
		font-weight: 600;
		font-size: 0.85rem;
		margin: 0;
	}
	.victim-list {
		max-height: 220px;
		overflow-y: auto;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-surface);
	}
	.victim {
		display: flex !important;
		flex-direction: row !important;
		align-items: center;
		gap: 10px;
		padding: 10px 12px;
		border-left: 3px solid transparent;
		cursor: pointer;
		font-weight: 500 !important;
		margin: 0;
	}
	.victim:hover {
		background: var(--pl-raised);
	}
	.victim:has(input:checked) {
		background: var(--pl-raised);
		border-left-color: var(--pl-seal);
		font-weight: 600 !important;
	}
	.victim input {
		accent-color: var(--pl-seal);
		min-height: 0;
	}
	.pl-error {
		margin-top: 12px;
	}
	@media (max-width: 900px) {
		.stats {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
