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
			const [s, p] = await Promise.all([api.getStats(), api.listPapers()]);
			stats = s;
			papers = p;
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

		<details class="danger">
			<summary>Danger zone: delete a paper</summary>
			<div class="danger-body">
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
