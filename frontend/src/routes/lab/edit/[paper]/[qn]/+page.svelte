<script>
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import katex from 'katex';
	import 'katex/dist/katex.min.css';
	import { MOCK_QUESTION_TEX, MOCK_SOLUTION_TEX, MOCK_FIGURES, mockTexToHtml } from '$lib/mockTex.js';

	/**
	 * MOCK workspace (exp/tex-editor): layout + interactions only.
	 * Hardcoded sample TeX, client-side mock preview, no API calls,
	 * nothing persisted. Real loading/preview/save waits for approval.
	 */

	const paper = $derived($page.params.paper ?? '?');
	const qn = $derived($page.params.qn ?? '?');
	const backParam = $derived($page.url.searchParams.get('back') ?? '');
	const backHref = $derived(
		backParam === '/search' ? `/search/${paper}/${encodeURIComponent(qn)}` : `/archive/${paper}?q=${encodeURIComponent(qn)}`
	);

	let part = $state($page.url.searchParams.get('part') === 'solution' ? 'solution' : 'question');
	const baseline = $state({ question: MOCK_QUESTION_TEX, solution: MOCK_SOLUTION_TEX });
	const drafts = $state({ question: MOCK_QUESTION_TEX, solution: MOCK_SOLUTION_TEX });

	const draft = $derived(drafts[part]);
	const dirty = $derived(drafts.question !== baseline.question || drafts.solution !== baseline.solution);
	const partDirty = $derived(drafts[part] !== baseline[part]);
	const fileName = $derived(part === 'question' ? 'question.tex' : 'solution.tex');
	const lineCount = $derived(draft.split('\n').length);

	let saveState = $state('saved'); // saved | dirty | saving
	let toast = $state('');
	let toastTimer = null;
	let previewHtml = $state('');
	let previewStale = $state(false);
	let previewTimer = null;
	let previewEl = $state(null);
	let mobileTab = $state('edit'); // edit | preview (narrow screens only)
	let pendingNav = $state(null); // { type: 'part', value } | { type: 'back' }

	function showToast(msg) {
		toast = msg;
		clearTimeout(toastTimer);
		toastTimer = setTimeout(() => (toast = ''), 3200);
	}

	function queuePreview() {
		previewStale = true;
		clearTimeout(previewTimer);
		previewTimer = setTimeout(() => {
			previewHtml = mockTexToHtml(drafts[part]);
			previewStale = false;
		}, 300);
	}

	function onInput(value) {
		drafts[part] = value;
		saveState = drafts.question !== baseline.question || drafts.solution !== baseline.solution ? 'dirty' : 'saved';
		queuePreview();
	}

	function switchPart(next) {
		if (next === part) return;
		if (dirty) {
			pendingNav = { type: 'part', value: next };
			return;
		}
		part = next;
		mobileTab = 'edit';
		queuePreview();
	}

	function confirmNav() {
		if (!pendingNav) return;
		// Discard all mock edits, then follow through.
		drafts.question = baseline.question;
		drafts.solution = baseline.solution;
		saveState = 'saved';
		const nav = pendingNav;
		pendingNav = null;
		if (nav.type === 'part') {
			part = nav.value;
			queuePreview();
		} else {
			window.location.href = backHref;
		}
	}

	function mockSave() {
		if (saveState === 'saving') return;
		saveState = 'saving';
		setTimeout(() => {
			saveState = 'saved';
			showToast('Mock save — nothing was persisted.');
		}, 600);
	}

	function mockDiscard() {
		drafts[part] = baseline[part];
		saveState = drafts.question !== baseline.question || drafts.solution !== baseline.solution ? 'dirty' : 'saved';
		queuePreview();
		showToast('Draft reset to the mock original.');
	}

	async function copyFig(name) {
		const snippet = `\\includegraphics{${name}}`;
		try {
			await navigator.clipboard.writeText(snippet);
		} catch {
			const ta = document.createElement('textarea');
			ta.value = snippet;
			document.body.appendChild(ta);
			ta.select();
			document.execCommand('copy');
			ta.remove();
		}
		showToast(`Copied ${snippet} — paste into the editor.`);
	}

	function onKey(e) {
		if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
			e.preventDefault();
			mockSave();
		}
	}

	$effect(() => {
		// Fill KaTeX placeholders after each preview render (same call as Segments).
		if (!previewEl) return;
		void previewHtml;
		for (const node of previewEl.querySelectorAll('.pl-math, .pl-math-block')) {
			if (node.dataset.done) continue;
			const tex = decodeURIComponent(node.dataset.tex || '');
			try {
				node.innerHTML = katex.renderToString(tex, {
					displayMode: node.classList.contains('pl-math-block'),
					throwOnError: false
				});
			} catch {
				node.innerHTML = '';
			}
			node.dataset.done = '1';
		}
	});

	$effect(() => {
		// Warn on reload/close with unsaved mock edits.
		const handler = (e) => {
			if (dirty) e.preventDefault();
		};
		window.addEventListener('beforeunload', handler);
		return () => window.removeEventListener('beforeunload', handler);
	});

	onMount(() => {
		// Initial mock preview.
		previewHtml = mockTexToHtml(drafts[part]);
	});
</script>

<svelte:head><title>Mock TeX editor - Paper {paper} Q{qn} - PaperLab</title></svelte:head>
<svelte:window onkeydown={onKey} />

<div class="ws">
	<header class="topbar">
		{#if dirty}
			<a class="back" href={backHref} onclick={(e) => { e.preventDefault(); pendingNav = { type: 'back' }; }}>← Back</a>
		{:else}
			<a class="back" href={backHref}>← Back</a>
		{/if}
		<span class="ident pl-mono">Paper {paper} · Q{qn}</span>
		<span class="mockbadge">Mock</span>
		<div class="seg" role="group" aria-label="Choose file">
			<button type="button" class:active={part === 'question'} onclick={() => switchPart('question')}>Question</button>
			<button type="button" class:active={part === 'solution'} onclick={() => switchPart('solution')}>Solution</button>
		</div>
		<div class="figstrip" aria-label="Figures in this question (mock)">
			<span class="figlabel">Figures</span>
			{#each MOCK_FIGURES as f (f)}
				<button
					type="button"
					class="figchip"
					title={`${f} — click to copy \\includegraphics`}
					onclick={() => copyFig(f)}
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/></svg>
					<span>{f}</span>
				</button>
			{/each}
			<a class="managelink" href={backHref} title="Open Manage figures in the reader">Manage figures</a>
		</div>
		<span class="status" data-state={saveState} role="status">
			{#if saveState === 'saving'}Saving…
			{:else if dirty}Unsaved changes
			{:else}Saved{/if}
		</span>
		<div class="actions">
			<button type="button" class="pl-btn" disabled={!dirty} onclick={mockDiscard}>Discard</button>
			<button type="button" class="pl-btn pl-btn-primary" disabled={!dirty || saveState === 'saving'} onclick={mockSave}>
				{saveState === 'saving' ? 'Saving…' : 'Save'}
			</button>
		</div>
	</header>

	<nav class="mobtabs" aria-label="Workspace view">
		<button type="button" class:active={mobileTab === 'edit'} onclick={() => (mobileTab = 'edit')}>Editor</button>
		<button type="button" class:active={mobileTab === 'preview'} onclick={() => (mobileTab = 'preview')}>
			Preview{#if previewStale}…{/if}
		</button>
	</nav>

	<div class="split">
		<section class="pane editorpane" class:active={mobileTab === 'edit'} aria-label="TeX editor">
			<div class="panehead">
				<span class="pl-mono">{fileName}</span>
				<span class="pl-sub">{lineCount} lines{#if partDirty} · edited{/if}</span>
			</div>
			<textarea
				class="editor"
				wrap="off"
				spellcheck="false"
				autocomplete="off"
				autocapitalize="off"
				aria-label={`Edit ${fileName} (mock)`}
				value={draft}
				oninput={(e) => onInput(e.currentTarget.value)}
			></textarea>
		</section>

		<section class="pane previewpane" class:active={mobileTab === 'preview'} aria-label="Preview" aria-live="polite">
			<div class="panehead">
				<span>Preview</span>
				<span class="pl-sub">{previewStale ? 'Updating…' : 'Mock render · reader styles'}</span>
			</div>
			<div class="paper" bind:this={previewEl}>
				{@html previewHtml}
			</div>
		</section>
	</div>

	{#if toast}
		<p class="toast" role="status">{toast}</p>
	{/if}

	{#if pendingNav}
		<div class="overlay" role="dialog" aria-modal="true" aria-label="Unsaved changes">
			<div class="dialog">
				<h2>Discard unsaved mock edits?</h2>
				<p class="pl-sub">You have unsaved changes in this mock workspace. They were never persisted, so leaving loses the draft text.</p>
				<div class="dialogrow">
					<button type="button" class="pl-btn" onclick={() => (pendingNav = null)}>Keep editing</button>
					<button type="button" class="pl-btn pl-btn-primary" onclick={confirmNav}>Discard changes</button>
				</div>
			</div>
		</div>
	{/if}
</div>

<style>
	.ws {
		min-height: 100dvh;
		display: flex;
		flex-direction: column;
		background: var(--pl-paper);
		color: var(--pl-ink);
	}
	.topbar {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		padding: 10px 16px;
		background: var(--pl-surface);
		border-bottom: 1px solid var(--pl-line);
		position: sticky;
		top: 0;
		z-index: 20;
	}
	.back {
		font-weight: 600;
		font-size: 0.85rem;
		white-space: nowrap;
	}
	.ident {
		font-size: 0.82rem;
		color: var(--pl-ink-soft);
		white-space: nowrap;
	}
	.mockbadge {
		font-size: 0.7rem;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--pl-ochre);
		background: var(--pl-ochre-soft);
		border-radius: var(--pl-radius-pill);
		padding: 2px 10px;
		white-space: nowrap;
	}
	h2 .mockbadge {
		vertical-align: middle;
	}
	.seg {
		display: inline-flex;
		background: var(--pl-raised);
		border-radius: var(--pl-radius-pill);
		padding: 3px;
		gap: 2px;
	}
	.seg button {
		border: none;
		background: none;
		border-radius: var(--pl-radius-pill);
		padding: 6px 14px;
		min-height: 0;
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
		cursor: pointer;
		white-space: nowrap;
	}
	.seg button.active {
		background: var(--pl-surface);
		color: var(--pl-ink);
		box-shadow: var(--pl-shadow-sm);
	}
	.figstrip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
		min-width: 0;
	}
	.figlabel {
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
		white-space: nowrap;
	}
	.figchip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		max-width: 190px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		background: var(--pl-surface);
		padding: 4px 10px 4px 8px;
		min-height: 0;
		font-size: 0.76rem;
		font-family: var(--pl-font-mono);
		color: var(--pl-ink-soft);
		cursor: pointer;
		white-space: nowrap;
	}
	.figchip:hover {
		color: var(--pl-seal);
		border-color: var(--pl-seal);
	}
	.figchip svg {
		width: 13px;
		height: 13px;
		flex-shrink: 0;
	}
	.figchip span {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.managelink {
		font-size: 0.78rem;
		font-weight: 600;
		white-space: nowrap;
	}
	.status {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
		white-space: nowrap;
	}
	.status[data-state='dirty'] {
		color: var(--pl-ochre);
	}
	.status[data-state='saving'] {
		color: var(--pl-seal);
	}
	.actions {
		margin-left: auto;
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.mobtabs {
		display: none;
	}
	.split {
		flex: 1;
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0;
		min-height: 0;
	}
	.pane {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
	}
	.editorpane {
		border-right: 1px solid var(--pl-line);
	}
	.panehead {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
		padding: 10px 16px 6px;
		font-size: 0.82rem;
		font-weight: 600;
	}
	.panehead .pl-sub {
		font-weight: 400;
	}
	.editor {
		flex: 1;
		margin: 0 16px 16px;
		padding: 16px;
		min-height: 50dvh;
		resize: none;
		font-family: var(--pl-font-mono);
		font-size: 0.86rem;
		line-height: 1.7;
		color: var(--pl-ink);
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		overflow: auto;
		white-space: pre;
	}
	.editor:focus {
		outline: 2px solid var(--pl-focus);
		outline-offset: 1px;
	}
	.paper {
		flex: 1;
		margin: 0 16px 16px;
		padding: 24px 26px;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		font-size: 17.5px;
		line-height: 1.7;
		overflow-y: auto;
		min-height: 50dvh;
	}
	.paper :global(p) {
		margin: 0.75em 0;
	}
	.paper :global(p:first-child) {
		margin-top: 0;
	}
	.paper :global(.pl-math-block) {
		display: block;
		text-align: center;
		margin: 0.75em 0;
	}
	.paper :global(.mockfig) {
		margin: 18px 0;
		text-align: center;
	}
	.paper :global(.mockfig-box) {
		display: flex;
		align-items: center;
		justify-content: center;
		max-width: 360px;
		height: 160px;
		margin: 0 auto 6px;
		border: 1px dashed var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-raised);
		color: var(--pl-ink-soft);
		font-size: 0.85rem;
	}
	.paper :global(figcaption) {
		font-size: 0.75rem;
		color: var(--pl-ink-soft);
	}
	.toast {
		position: fixed;
		bottom: 20px;
		left: 50%;
		transform: translateX(-50%);
		background: var(--pl-ink);
		color: var(--pl-paper);
		border-radius: var(--pl-radius-pill);
		padding: 8px 18px;
		font-size: 0.85rem;
		margin: 0;
		z-index: 50;
		max-width: 90vw;
		text-align: center;
	}
	.overlay {
		position: fixed;
		inset: 0;
		z-index: 60;
		background: rgb(0 0 0 / 0.45);
		display: grid;
		place-items: center;
		padding: 20px;
	}
	.dialog {
		background: var(--pl-surface);
		border-radius: var(--pl-radius-lg);
		box-shadow: var(--pl-shadow-md);
		padding: 22px 24px;
		max-width: 440px;
		width: 100%;
	}
	.dialog h2 {
		font-size: 1.1rem;
		margin: 0 0 8px;
	}
	.dialog .pl-sub {
		margin: 0 0 16px;
	}
	.dialogrow {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		flex-wrap: wrap;
	}
	@media (max-width: 899px) {
		.mobtabs {
			display: flex;
			gap: 4px;
			padding: 8px 16px 0;
		}
		.mobtabs button {
			flex: 1;
			border: 1px solid var(--pl-line);
			background: var(--pl-surface);
			border-radius: var(--pl-radius-sm);
			padding: 8px;
			font-size: 0.85rem;
			font-weight: 600;
			color: var(--pl-ink-soft);
			cursor: pointer;
		}
		.mobtabs button.active {
			color: var(--pl-seal);
			border-color: var(--pl-seal);
		}
		.split {
			grid-template-columns: 1fr;
			padding-bottom: 16px;
		}
		.editorpane,
		.previewpane {
			display: none;
		}
		.editorpane.active,
		.previewpane.active {
			display: flex;
		}
		.editorpane {
			border-right: none;
		}
		.editor,
		.paper {
			min-height: 60dvh;
		}
	}
</style>
