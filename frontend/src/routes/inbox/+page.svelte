<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { inboxItems, role, loginOpen } from '$lib/stores.js';
	import Segments from '$lib/components/Segments.svelte';
	import ClassifyForm from '$lib/components/ClassifyForm.svelte';

	const isArchivist = $derived($role === 'archivist');

	let index = $state(0);
	let loading = $state(true);
	let error = $state('');

	const items = $derived($inboxItems ?? []);
	const current = $derived(items[index]);

	async function load(force = false) {
		loading = true;
		error = '';
		try {
			if (force || $inboxItems === null) {
				inboxItems.set(await api.getInbox());
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

	function dropCurrent() {
		inboxItems.update((list) =>
			(list ?? []).filter((q) => q.number !== current.number)
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
	<p class="pl-sub">{index + 1} of {items.length} here</p>
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
			<svelte:boundary>
				<Segments segments={current.question} />
				{#key current.paperId + current.number}
					<ClassifyForm
						paperId={current.paperId}
						number={current.number}
						initial={current}
						onSaved={dropCurrent}
					/>
				{/key}
				{#snippet failed()}
					<p class="pl-error" role="alert">Could not display this question. Skipping is safe — the data is unchanged.</p>
				{/snippet}
			</svelte:boundary>
		</div>
	{/if}
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.stepper {
		display: flex;
		gap: 8px;
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
</style>
