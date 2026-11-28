<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { appStatus, refreshStatus, toast } from '$lib/stores.js';
	import { STAGE_LABEL, statusLabel, money, estimate } from '$lib/labels.js';
	import SetupNotice from '$lib/components/SetupNotice.svelte';

	let data = $state(null);
	let cart = $state(null);
	let error = $state('');
	let busy = $state(false);
	let logs = $state({}); // job id -> text
	let startError = $state('');

	const s = $derived($appStatus);
	const missing = $derived(s?.missing ?? []);
	const queue = $derived(data?.queue ?? s?.queue);
	const stages = $derived(data?.stages ?? []);
	const jobs = $derived(data?.jobs ?? []);
	const pending = $derived(jobs.filter((j) => j.status === 'queued').length);
	const active = $derived(jobs.some((j) => j.status === 'running'));
	const cartParts = $derived(cart?.items?.length ?? 0);
	const est = $derived(estimate(cart?.questions ?? 0));
	const systemic = $derived(queue?.paused && queue?.kind && queue.kind !== 'user' && queue.reason);

	async function load() {
		try {
			[data, cart] = await Promise.all([api.jobs(), api.cart()]);
			error = '';
		} catch (e) {
			error = e.message;
		}
	}

	async function act(fn, okText) {
		busy = true;
		startError = '';
		try {
			data = await fn();
			cart = await api.cart();
			if (okText) toast(okText, 'ok');
		} catch (e) {
			startError = e.message;
		} finally {
			busy = false;
			refreshStatus();
		}
	}

	function start() {
		const msg =
			`Process ${cartParts} part${cartParts === 1 ? '' : 's'} (${cart.questions} questions)?\n\n` +
			`This makes paid model calls with your Meta API key: about ${est.usd} (${est.inrGst} incl. GST).\n` +
			`Finished parts are published to your PaperLab server.`;
		if (!confirm(msg)) return;
		act(api.start, 'Processing started.');
	}

	async function showLog(job) {
		if (logs[job.id] !== undefined) {
			const { [job.id]: _, ...rest } = logs;
			logs = rest;
			return;
		}
		try {
			logs = { ...logs, [job.id]: (await api.log(job.id)).log || '(no log yet)' };
		} catch (e) {
			toast(e.message, 'warn');
		}
	}

	async function retry(job) {
		await act(() => api.retry(job.id), `Part ${job.part} queued again.`);
	}

	async function remove(job) {
		if (!confirm(`Remove ${job.source} — Part ${job.part} from the list?\n\nIts run folder (and anything already paid for) is kept on disk; adding it again resumes from there.`)) return;
		await act(() => api.removeJob(job.id));
	}

	const stageState = (job, stage) => {
		if (job.done.includes(stage)) return 'done';
		if (job.stage === stage) {
			if (job.status === 'running') return 'now';
			if (job.status === 'failed') return 'fail';
			if (job.status === 'queued' && job.error) return 'wait';
		}
		return 'todo';
	};

	onMount(() => {
		load();
		let timer;
		const tick = async () => {
			await load();
			for (const id of Object.keys(logs)) {
				const job = jobs.find((j) => String(j.id) === id);
				if (job?.status === 'running') logs = { ...logs, [id]: (await api.log(job.id)).log };
			}
			timer = setTimeout(tick, active || (!queue?.paused && pending) ? 2000 : 5000);
		};
		timer = setTimeout(tick, 2000);
		return () => clearTimeout(timer);
	});
</script>

<svelte:head><title>Process & Publish - EJEE Importer</title></svelte:head>

<h1>Process & Publish</h1>
<p class="pl-sub intro">
	Each part is transcribed, its figures cropped from original pixels, tagged, verified, bundled and published to your
	PaperLab server. If the key, link or password is wrong, the queue pauses; fix Settings and resume from the exact step
	that stopped. Finished work is never redone or billed twice.
</p>

<SetupNotice />

{#if error}
	<div class="pl-error" role="alert"><p>{error}</p><button type="button" class="pl-btn" onclick={load}>Retry</button></div>
{/if}

<section class="pl-card controls" aria-label="Queue">
	<div class="ready">
		{#if cartParts}
			<strong>{cartParts} part{cartParts === 1 ? '' : 's'} in the cart</strong>
			<span class="pl-sub">· {cart.questions} questions · about {est.usd} ({est.inrGst} incl. GST)</span>
		{:else}
			<strong>Cart is empty.</strong> <a href="/search">Add parts from Search</a>
		{/if}
		<p class="pl-sub state">
			Queue: {queue?.paused ? 'paused' : active ? 'processing' : pending ? 'starting…' : 'idle'}
			{#if pending}· {pending} waiting{/if}
		</p>
	</div>
	<div class="buttons">
		{#if cartParts}
			<button type="button" class="pl-btn pl-btn-primary" disabled={busy || missing.length > 0} onclick={start}
				title={missing.length ? 'Finish Settings first' : ''}>
				{busy ? 'Checking server and key…' : `Start processing ${cartParts} part${cartParts === 1 ? '' : 's'}`}
			</button>
		{/if}
		{#if queue?.paused && pending}
			<button type="button" class="pl-btn" class:pl-btn-primary={!cartParts} disabled={busy || missing.length > 0}
				onclick={() => act(api.resume, 'Queue resumed.')}>
				{busy ? 'Checking…' : 'Resume'}
			</button>
		{:else if !queue?.paused && (active || pending)}
			<button type="button" class="pl-btn" disabled={busy} onclick={() => act(api.pause, 'Pausing after the current step.')}>
				Pause
			</button>
		{/if}
	</div>
</section>

{#if startError}
	<div class="pl-error" role="alert">
		<strong>Not started.</strong>
		<p>{startError}</p>
		<a class="pl-btn" href="/settings">Open Settings</a>
	</div>
{/if}

{#if systemic && pending}
	<div class="pl-error paused" role="alert">
		<strong>Queue paused</strong>
		<p>{queue.reason}</p>
		<div class="row">
			<a class="pl-btn" href="/settings">Open Settings</a>
			<button type="button" class="pl-btn pl-btn-primary" disabled={busy || missing.length > 0}
				onclick={() => act(api.resume, 'Queue resumed.')}>Resume</button>
		</div>
	</div>
{/if}

{#if data && !jobs.length}
	<p class="pl-sub empty">No parts processed yet.</p>
{/if}

<ul class="jobs">
	{#each jobs as job (job.id)}
		<li class="pl-card job" class:fail={job.status === 'failed'}>
			<div class="jhead">
				<div class="title">
					<h2>{job.source} — Part {job.part}</h2>
					<p class="pl-sub">
						{job.questions} questions · {money(job.money)}{job.attempts > 1 ? ` · attempt ${job.attempts}` : ''}
					</p>
				</div>
				<span class={`status st-${job.status}`}>{statusLabel(job.status)}</span>
			</div>

			<ol class="steps" aria-label="Steps">
				{#each stages as st (st)}
					{@const state = stageState(job, st)}
					<li class={`step ${state}`} aria-current={state === 'now' ? 'step' : undefined}>
						<span class="dot" aria-hidden="true">{state === 'done' ? '✓' : state === 'fail' ? '!' : ''}</span>
						<span class="lbl">{STAGE_LABEL[st] ?? st}</span>
					</li>
				{/each}
			</ol>

			{#if job.error}
				<p class="msg" class:warn={job.status !== 'done'}>{job.error}</p>
			{/if}
			{#if job.detail?.errors?.length && job.status === 'failed'}
				<details>
					<summary>{job.detail.errors.length} verification finding(s)</summary>
					<ul class="errs">{#each job.detail.errors.slice(0, 40) as e}<li class="pl-mono">{e}</li>{/each}</ul>
				</details>
			{/if}

			{#if job.detail?.auto_approved?.length}
				<p class="pl-hint">
					Published without review: held figure(s) in Q{job.detail.auto_approved.join(', Q')} were approved
					automatically (recorded as “no human review” in the bundle).
				</p>
			{/if}

			{#if job.detail?.untagged?.length}
				<p class="pl-hint">
					Q{job.detail.untagged.join(', Q')}: the tagger chose no topic; published untagged to PaperLab's Tagging Inbox.
				</p>
			{/if}

			{#if job.receipt}
				<div class="pl-ok receipt">
					<strong>{job.receipt.already_imported ? 'Already in PaperLab' : 'Published to PaperLab'}</strong>
					{#each job.receipt.papers ?? [] as p}
						<span> · archive paper #{p.archive_paper} · {p.questions} questions</span>
					{/each}
					{#if job.receipt.merged_at}<span class="pl-sub"> · {job.receipt.merged_at}</span>{/if}
					{#if job.receipt.warnings?.length}<p class="pl-hint">{job.receipt.warnings.join('; ')}</p>{/if}
				</div>
			{/if}

			<div class="row">
				{#if job.status === 'failed'}
					<button type="button" class="pl-btn pl-btn-primary" disabled={busy} onclick={() => retry(job)}>
						Retry from {STAGE_LABEL[job.stage] ?? 'start'}
					</button>
				{/if}
				<button type="button" class="pl-btn" onclick={() => showLog(job)}>
					{logs[job.id] !== undefined ? 'Hide log' : 'Log'}
				</button>
				{#if job.status !== 'running'}
					<button type="button" class="pl-btn ghost" disabled={busy} onclick={() => remove(job)}>Remove</button>
				{/if}
			</div>
			{#if logs[job.id] !== undefined}
				<pre class="log">{logs[job.id]}</pre>
			{/if}
		</li>
	{/each}
</ul>

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.intro {
		margin-top: 0;
		max-width: 760px;
	}
	.controls {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 16px;
		flex-wrap: wrap;
		margin: 16px 0;
	}
	.state {
		margin: 4px 0 0;
		font-size: 0.85rem;
	}
	.buttons,
	.row {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
		align-items: center;
	}
	.paused,
	.pl-error {
		margin: 12px 0;
	}
	.paused p,
	.pl-error p {
		margin: 6px 0 10px;
	}
	.empty {
		margin-top: 20px;
	}
	.jobs {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.job {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.job.fail {
		border-color: var(--pl-ochre);
	}
	.jhead {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		align-items: flex-start;
	}
	h2 {
		font-size: 1.15rem;
	}
	.title p {
		margin: 2px 0 0;
		font-size: 0.82rem;
	}
	.status {
		border-radius: var(--pl-radius-pill);
		padding: 4px 12px;
		font-size: 0.78rem;
		font-weight: 600;
		background: var(--pl-raised);
		white-space: nowrap;
	}
	.st-running {
		background: var(--pl-seal-soft);
		color: var(--pl-seal);
	}
	.st-done {
		background: var(--pl-pine-soft);
		color: var(--pl-pine);
	}
	.st-failed {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.steps {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(8, 1fr);
		gap: 4px;
	}
	.step {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		position: relative;
		font-size: 0.72rem;
		color: var(--pl-ink-soft);
		text-align: center;
	}
	.step::before {
		content: '';
		position: absolute;
		top: 11px;
		left: -50%;
		width: 100%;
		height: 2px;
		background: var(--pl-line);
		z-index: 0;
	}
	.step:first-child::before {
		display: none;
	}
	.step.done::before,
	.step.now::before {
		background: var(--pl-pine);
	}
	.dot {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		background: var(--pl-surface);
		border: 2px solid var(--pl-line);
		font-size: 0.75rem;
		font-weight: 700;
		z-index: 1;
	}
	.step.done .dot {
		background: var(--pl-pine);
		border-color: var(--pl-pine);
		color: #fff;
	}
	[data-theme='dark'] .step.done .dot {
		color: #141311;
	}
	.step.now .dot {
		border-color: var(--pl-seal);
		background: var(--pl-seal-soft);
		animation: pulse 1.4s ease-in-out infinite;
	}
	.step.now .lbl {
		color: var(--pl-ink);
		font-weight: 600;
	}
	.step.fail .dot,
	.step.wait .dot {
		border-color: var(--pl-ochre);
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	@keyframes pulse {
		50% {
			box-shadow: 0 0 0 5px var(--pl-seal-soft);
		}
	}
	.msg {
		margin: 0;
		font-size: 0.88rem;
	}
	.msg.warn {
		color: var(--pl-ochre);
	}
	details summary {
		cursor: pointer;
		font-size: 0.85rem;
		font-weight: 600;
	}
	.errs {
		margin: 6px 0 0;
		padding-left: 18px;
		max-height: 220px;
		overflow: auto;
	}
	.receipt {
		font-size: 0.88rem;
	}
	.receipt .pl-hint {
		margin-top: 4px;
	}
	.ghost {
		color: var(--pl-ink-soft);
	}
	.log {
		margin: 0;
		max-height: 320px;
		overflow: auto;
		background: var(--pl-raised);
		border-radius: var(--pl-radius-sm);
		padding: 10px 12px;
		font-family: var(--pl-font-mono);
		font-size: 0.75rem;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	@media (max-width: 640px) {
		.steps {
			grid-template-columns: repeat(4, 1fr);
			row-gap: 10px;
		}
		.step:nth-child(5)::before {
			display: none;
		}
	}
</style>
