<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { role } from '$lib/stores.js';
	import StatCard from '$lib/components/StatCard.svelte';

	const isArchivist = $derived($role === 'archivist');

	let topics = $state([]);
	let usage = $state({});
	let path = $state([]);
	let loading = $state(true);
	let error = $state('');
	let message = $state('');

	// Add forms
	let newModule = $state('');
	let newChildName = $state('');
	let newChildDescr = $state('');

	// Edit form (bound when focus changes via keyed block)
	let editName = $state('');
	let editDescr = $state('');

	// Two-step delete arming (destructive actions need an explicit second click)
	let arming = $state(null);

	// Move form
	let moveDest = $state('');

	const byCode = $derived(Object.fromEntries(topics.map((t) => [t.code, t])));

	const childLevel = $derived.by(() => {
		const focus = path.length ? byCode[path[path.length - 1]] : null;
		if (!focus) return null;
		return { module: 'chapter', chapter: 'week', week: 'subtopic' }[focus.level] ?? null;
	});

	const childrenOf = (code) => topics.filter((t) => t.parent === code);
	const modules = $derived(topics.filter((t) => t.level === 'module'));
	const focus = $derived(path.length ? byCode[path[path.length - 1]] : null);
	const shown = $derived(focus ? childrenOf(focus.code) : modules);
	const crumbs = $derived(['All modules', ...path.map((c) => byCode[c]?.name || c)]);

	const moveOptions = $derived.by(() => {
		if (!focus) return [];
		if (focus.level === 'subtopic') {
			const chap = focus.code.split('.')[0];
			return topics.filter(
				(t) =>
					t.level === 'week' &&
					t.code.startsWith(chap + '-') &&
					t.code !== focus.parent
			);
		}
		if (focus.level === 'chapter') return modules;
		return [];
	});

	async function refresh() {
		arming = null;
		const [t, u] = await Promise.all([api.getTopics(), api.getTopicUsage()]);
		topics = t;
		usage = u;
		// Drop path entries that no longer exist (e.g. after a delete).
		path = path.filter((c) => byCode[c]);
		if (focus) {
			editName = focus.name;
			editDescr = focus.descr || '';
		}
		moveDest = '';
	}

	onMount(async () => {
		if (!isArchivist) {
			loading = false;
			return;
		}
		try {
			await refresh();
		} catch (e) {
			error = e.message;
		} finally {
			loading = false;
		}
	});

	function open(code) {
		arming = null;
		message = '';
		path = [...path, code];
		const node = byCode[code];
		if (node) {
			editName = node.name;
			editDescr = node.descr || '';
		}
		moveDest = '';
		message = '';
	}

	async function run(label, fn) {
		message = '';
		try {
			const out = await fn();
			await refresh();
			message = out;
		} catch (e) {
			message = `${label} failed: ${e.message}`;
		}
	}

	function remove(code) {
		if (arming !== code) {
			arming = code;
			message = '';
			return Promise.resolve();
		}
		arming = null;
		return run('Delete', async () => {
			await api.deleteTopic(code);
			path = path.filter((c) => c !== code);
			return `Deleted ${code}.`;
		});
	}

	function addModule() {
		if (!newModule.trim()) return;
		const name = newModule.trim();
		newModule = '';
		return run('Add', async () => {
			const { code } = await api.createTopic({ level: 'module', name });
			path = [code];
			return `Added ${code}.`;
		});
	}

	function addChild() {
		if (!focus || !childLevel || !newChildName.trim()) return;
		const name = newChildName.trim();
		const descr = newChildDescr.trim();
		newChildName = '';
		newChildDescr = '';
		return run('Add', async () => {
			const { code } = await api.createTopic({
				parent: focus.code,
				level: childLevel,
				name,
				descr
			});
			path = [...path, code];
			return `Added ${code}.`;
		});
	}

	function saveEdit() {
		if (!focus) return;
		return run('Save', async () => {
			const { rev } = await api.updateTopic(focus.code, {
				name: editName,
				descr: focus.level === 'subtopic' ? editDescr : '',
				rev: focus.rev
			});
			return `Saved ${focus.code} (rev ${rev}).`;
		});
	}

	function move() {
		if (!focus || !moveDest) return;
		return run('Move', async () => {
			await api.moveTopic(focus.code, moveDest);
			if (focus.level === 'chapter') path = [moveDest, focus.code];
			else path = [...path.slice(0, -1), moveDest, focus.code];
			return `Moved to ${moveDest}.`;
		});
	}
</script>

<svelte:head><title>Syllabus Map - PaperLab</title></svelte:head>

<h1>Syllabus Map</h1>

{#if !isArchivist}
	<div class="pl-card">
		<p>This area needs archivist access. Use the role switch in the sidebar to log in.</p>
	</div>
{:else if loading}
	<p class="pl-sub">Loading topics…</p>
{:else if error}
	<div class="pl-error" role="alert">
		<strong>Could not load topics.</strong>
		<p class="pl-mono">{error}</p>
	</div>
{:else}
	<div class="stats">
		<StatCard label="Modules" value={topics.filter((t) => t.level === 'module').length} />
		<StatCard label="Chapters" value={topics.filter((t) => t.level === 'chapter').length} />
		<StatCard label="Topics" value={topics.filter((t) => t.level === 'subtopic').length} />
		<StatCard label="Files & questions" value={topics.length} />
	</div>

	<p class="pl-mono pl-sub">{crumbs.join(' / ')}</p>
	{#if message}<p class="pl-sub" role="status">{message}</p>{/if}

	{#if path.length > 0}
		<div class="row">
			<button type="button" class="pl-btn" onclick={() => (path = path.slice(0, -1))}>
				Back
			</button>
		</div>
	{/if}

	{#if focus}
		<div class="pl-card focus">
			<div class="focus-head">
				<div>
					<h2>{focus.code} - {focus.name}</h2>
					<p class="pl-sub">{focus.level} · rev {focus.rev}</p>
					{#if focus.level === 'subtopic' && focus.descr}
						<p class="pl-sub">{focus.descr}</p>
					{/if}
				</div>
				<div class="focus-actions">
					<button type="button" class="pl-btn" onclick={() => (path = path.slice(0, -1))}>Up</button>
					<button type="button" class="pl-btn pl-btn-danger" onclick={() => remove(focus.code)}>{arming === focus.code ? 'Confirm delete' : 'Delete'}</button>
				</div>
			</div>
			{#key focus.code + focus.rev}
				<div class="edit">
					<label>
						Name
						<input type="text" bind:value={editName} />
					</label>
					{#if focus.level === 'subtopic'}
						<label>
							Description (classifying guide for the AI tagger)
							<textarea bind:value={editDescr} rows="3"></textarea>
						</label>
					{/if}
					<div><button type="button" class="pl-btn pl-btn-primary" onclick={saveEdit}>Save</button></div>
				</div>
			{/key}
		</div>
	{/if}

	<div class="grid">
		{#each shown as topic (topic.code)}
			<div class="mod">
				<button type="button" class="mod-open" onclick={() => open(topic.code)}>
					<span class="mod-code pl-mono">{topic.code}</span>
					<span class="mod-name">{topic.name}</span>
					<span class="mod-count pl-sub">{childrenOf(topic.code).length} inside</span>
				</button>
				<button
					type="button"
					class="pl-btn mod-del"
					aria-label={arming === topic.code ? `Confirm delete ${topic.code}` : `Delete ${topic.code}`}
					onclick={() => remove(topic.code)}
				>
					{arming === topic.code ? 'Confirm delete' : 'Delete'}
				</button>
			</div>
		{/each}
	</div>

	<div class="pl-card add">
		{#if !focus}
			<h3>Add a module</h3>
			<div class="row">
				<input type="text" bind:value={newModule} placeholder="New module name…" aria-label="New module name" />
				<button type="button" class="pl-btn pl-btn-primary" disabled={!newModule.trim()} onclick={addModule}>Add</button>
			</div>
		{:else if childLevel}
			<h3>Add a {childLevel}</h3>
			<label>
				Name
				<input type="text" bind:value={newChildName} placeholder={`New ${childLevel} name…`} />
			</label>
			{#if childLevel === 'subtopic'}
				<label>
					Description (classifying guide for the AI tagger)
					<textarea bind:value={newChildDescr} rows="2" placeholder="What this topic covers…"></textarea>
				</label>
			{/if}
			<div class="row">
				<button type="button" class="pl-btn pl-btn-primary" disabled={!newChildName.trim()} onclick={addChild}>Add</button>
			</div>
		{:else}
			<p class="pl-sub">Subtopics have no children.</p>
		{/if}
	</div>

	{#if focus && (focus.level === 'subtopic' || focus.level === 'chapter')}
		<div class="pl-card add">
			<h3>Move this {focus.level}</h3>
			{#if moveOptions.length === 0}
				<p class="pl-sub">No valid destination.</p>
			{:else}
				<div class="row">
					<select bind:value={moveDest} aria-label="Destination">
						<option value="">Choose…</option>
						{#each moveOptions as dest (dest.code)}
							<option value={dest.code}>{dest.code} - {dest.name}</option>
						{/each}
					</select>
					<button type="button" class="pl-btn" disabled={!moveDest} onclick={move}>Move</button>
				</div>
			{/if}
			<p class="pl-sub">
				Used by {usage[focus.code] ?? 0} question tag(s), {childrenOf(focus.code).length} children.
				Delete is refused while tags or children exist - retag or move them first. Codes never change, so existing tags keep working.
			</p>
		</div>
	{/if}
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.row {
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
		margin-top: 8px;
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 12px;
		margin: 20px 0;
	}
	.focus {
		margin: 12px 0;
	}
	.focus-head {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		align-items: flex-start;
	}
	.focus-head h2 {
		font-size: 1.25rem;
		margin-bottom: 2px;
	}
	.focus-actions {
		display: flex;
		gap: 8px;
		flex-shrink: 0;
	}
	.edit {
		display: flex;
		flex-direction: column;
		gap: 10px;
		margin-top: 12px;
		border-top: 1px solid var(--pl-line);
		padding-top: 12px;
	}
	.edit label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.85rem;
		font-weight: 600;
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 12px;
		margin-top: 12px;
	}
	.mod {
		display: flex;
		gap: 8px;
		align-items: stretch;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		padding: 8px;
	}
	.mod:hover {
		box-shadow: var(--pl-shadow-sm);
	}
	.mod-open {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 2px;
		text-align: left;
		background: none;
		border: none;
		padding: 8px;
		min-height: 0;
	}
	.mod-name {
		font-weight: 600;
		font-size: 1.05rem;
	}
	.mod-del {
		align-self: center;
	}
	.add {
		margin-top: 12px;
	}
	.add h3 {
		font-size: 1.05rem;
		margin-bottom: 8px;
	}
	.add label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 0.85rem;
		font-weight: 600;
		margin-top: 8px;
	}
	.pl-btn-danger {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.pl-btn-danger:hover {
		background: var(--pl-seal);
		color: #fff;
	}
	@media (max-width: 900px) {
		.stats,
		.grid {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
