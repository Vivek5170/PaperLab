<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import TopicPicker from '$lib/components/TopicPicker.svelte';

	/** One Save writes type + difficulty + topics + suggestion (PATCH). */
	let {
		paperId,
		number,
		initial = { qtype: 'unknown', difficulty: null, suggestion: '', topics: [] },
		onSaved = () => {}
	} = $props();

	let qtypes = $state([]);
	let difficulties = $state([]);
	let options = $state([]); // [{code, path}]
	let qtype = $state(initial.qtype ?? 'unknown');
	let difficulty = $state(initial.difficulty ?? '');
	let topicCodes = $state([...new Set((initial.topics ?? []).map((t) => t.code))]);
	let suggestion = $state(initial.suggestion ?? '');
	let saving = $state(false);
	let message = $state('');

	onMount(async () => {
		try {
			const [meta, topics] = await Promise.all([api.getMeta(), api.getTopics()]);
			qtypes = meta.qtypes;
			difficulties = meta.difficulties;
			options = topics
				.filter((t) => t.level === 'subtopic')
				.map((t) => ({ code: t.code, path: t.name }));
		} catch {
			message = 'Could not load topic options.';
		}
	});

	async function save() {
		saving = true;
		message = '';
		try {
			const detail = await api.classifyQuestion(paperId, number, {
				qtype,
				difficulty: difficulty || null,
				topicCodes,
				suggestion: suggestion.trim()
			});
			message = `Saved ${number}.`;
			onSaved(detail);
		} catch (e) {
			message = `Save failed: ${e.message}`;
		} finally {
			saving = false;
		}
	}
</script>

<div class="form">
	<p class="pl-sub">First topic is the primary one.</p>
	<label>
		Question type
		<select bind:value={qtype}>
			{#each qtypes as qt (qt)}
				<option value={qt}>{qt}</option>
			{/each}
		</select>
	</label>
	<label>
		Difficulty
		<select bind:value={difficulty}>
			<option value="">Not graded</option>
			{#each difficulties as d (d)}
				<option value={d}>{d}</option>
			{/each}
		</select>
	</label>
	<label class="topics-label">
		Topics
		<TopicPicker {options} bind:value={topicCodes} />
	</label>
	<label>
		Suggestion (why nothing fit / proposed new topic)
		<textarea bind:value={suggestion} rows="2"></textarea>
	</label>
	<div class="row">
		<button type="button" class="pl-btn pl-btn-primary" disabled={saving} onclick={save}>
			{saving ? 'Saving…' : 'Save'}
		</button>
		{#if message}<span class="pl-sub" role="status">{message}</span>{/if}
	</div>
</div>

<style>
	.form {
		display: flex;
		flex-direction: column;
		gap: 10px;
		margin-top: 12px;
		border-top: 1px solid var(--pl-line);
		padding-top: 12px;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.85rem;
		font-weight: 600;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 12px;
	}
</style>
