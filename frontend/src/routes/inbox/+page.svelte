<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { inboxItems, role, loginOpen } from '$lib/stores.js';
	import Segments from '$lib/components/Segments.svelte';
	import ClassifyForm from '$lib/components/ClassifyForm.svelte';

	const isArchivist = $derived($role === 'archivist');

	let index = $state(0);
	let loading = $state(true);
	let loadingDetail = $state(false);
	let error = $state('');
	let showSolution = $state(false);
	let lastShown = $state(null);

	const items = $derived($inboxItems ?? []);
	const current = $derived(items[index]);

	$effect(() => {
		if (current && lastShown !== current.number) {
			lastShown = current.number;
			showSolution = false;
			loadDetail();
		}
	});

	async function load(force = false) {
		loading = true;
		error = '';
		try {
			if (force || $inboxItems === null) {
				const res = await api.getInbox();
				inboxItems.set(Array.isArray(res) ? res : res.items);
			}
		} catch (e) {
			if (e.message.startsWith('401')) {
				role.set('student');
				loginOpen.set(true);
				error = 'Session expired - log in again as archivist.';
			} else {
				error = e.message;
			}
		} finally {
			loading = false;
		}
	}

	let detail = $state(null);

	async function loadDetail() {
		detail = null;
		if (!current) return;
		loadingDetail = true;
		try {
			detail = await api.getQuestion(current.paperId, current.number);
		} catch (e) {
			error = e.message;
		} finally {
			loadingDetail = false;
		}
	}

	function dropCurrent() {
		inboxItems.update((list) =>
			(list ?? []).filter((q) => q.number !== current?.number || q.paperId !== current?.paperId)
		);
		if (index >= items.length) index = Math.max(0, items.length - 1);
	}

	onMount(async () => {
		if (!isArchivist) {
			loading = false;
			return;
		}
		await load();
	});
</script>

<svelte:head><title>Tagging Inbox - PaperLab</title></svelte:head>

<h1>Tagging Inbox</h1>

{#if !isArchivist && !error}
	<div class="pl-card">
		<p>This area needs archivist access. Use the role switch in the sidebar to log in.</p>
	</div>
{:else if loading}
	<p class="pl-sub">Loading queue…</p>
{:else if error}
	<div class="pl-error" role="alert">
		<strong>Could not load the queue.</strong>
		<p class="pl-mono">{error}</p>
		<p><button type="button" class="pl-btn" onclick={() => load(true)}>Retry</button></p>
	</div>
{:else if items.length === 0}
	<div class="pl-card"><p>Fully tagged - nothing left in the queue.</p></div>
{:else}
	<p class="pl-sub queue-pos">
		<input
			type="number"
			min="1"
			max={items.length}
			value={index + 1}
			aria-label="Go to question number in queue"
			onchange={(e) => {
				const n = Number(e.currentTarget.value);
				if (Number.isFinite(n)) {
					index = Math.min(Math.max(Math.floor(n), 1), items.length) - 1;
				}
				e.currentTarget.value = String(index + 1);
			}}
		/>
		<span>of {items.length} here</span>
	</p>
	<div class="stepper">
		<button
			type="button"
			class="pl-btn"
			disabled={index === 0}
			onclick={() => (index -= 1)}
		>
			Previous
		</button>
		<button
			type="button"
			class="pl-btn"
			disabled={index === items.length - 1}
			onclick={() => (index += 1)}
		>
			Next
		</button>
	</div>
	{#if current}
		<div class="pl-card">
			<h2>Paper #{current.paperId} - Question {current.number}</h2>
			{#if current.suggestion}
				<p class="suggest">Agent suggestion: {current.suggestion}</p>
			{/if}
			{#if loadingDetail || !detail}
				<p class="pl-sub">Loading question…</p>
			{:else}
			<svelte:boundary>
				<Segments segments={detail.question} />
				<div class="row">
					<button
						type="button"
						class="pl-btn"
						onclick={() => (showSolution = !showSolution)}
					>
						{showSolution ? 'Hide solution' : 'Show solution'}
					</button>
				</div>
				{#if showSolution}
					<div class="solution">
						<Segments segments={detail.solution} />
					</div>
				{/if}
				{#key detail.paperId + detail.number}
					<ClassifyForm
						paperId={detail.paperId}
						number={detail.number}
						initial={detail}
						onSaved={dropCurrent}
					/>
				{/key}
				{#snippet failed()}
					<p class="pl-error" role="alert">Could not display this question. Skipping is safe — the data is unchanged.</p>
				{/snippet}
				</svelte:boundary>
			{/if}
		</div>
	{/if}
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.queue-pos {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.queue-pos input {
		width: 64px;
		padding: 6px 8px;
		min-height: 0;
	}
	.stepper {
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
		margin: 12px 0;
	}
	.pl-card h2 {
		font-size: 1.2rem;
		margin-bottom: 8px;
	}
	.suggest {
		border-left: 3px solid var(--pl-ochre);
		padding-left: 12px;
		color: var(--pl-ink-soft);
	}
	.row {
		display: flex;
		gap: 8px;
		margin: 12px 0 4px;
	}
	.solution {
		border-top: 1px solid var(--pl-line);
		padding-top: 12px;
		margin-bottom: 4px;
	}
</style>
