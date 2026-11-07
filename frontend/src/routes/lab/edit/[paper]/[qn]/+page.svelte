<script>
	import { page } from '$app/stores';
	import { beforeNavigate, goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { dropQuestionDetail } from '$lib/questionCache.js';
	import Segments from '$lib/components/Segments.svelte';

	/**
	 * Experimental TeX workspace (exp/tex-editor): real backend wiring.
	 * GET raw tex, POST draft preview (read-only), PATCH save with
	 * sha-guarded concurrency. Reader + pipeline untouched.
	 */

	const paper = $derived($page.params.paper ?? '?');
	const qn = $derived($page.params.qn ?? '?');
	const backParam = $derived($page.url.searchParams.get('back') ?? '');
	const backHref = $derived(
		backParam === '/search' ? `/search/${paper}/${encodeURIComponent(qn)}` : `/archive/${paper}?q=${encodeURIComponent(qn)}`
	);

	let part = $state($page.url.searchParams.get('part') === 'solution' ? 'solution' : 'question');
	const baseline = $state({ question: '', solution: '' });
	const drafts = $state({ question: '', solution: '' });
	const shas = $state({ question: null, solution: null });
	let loaded = $state({ question: false, solution: false });
	let loadError = $state('');
	let figures = $state([]);

	const draft = $derived(drafts[part]);
	const dirty = $derived(
		(loaded.question && drafts.question !== baseline.question) ||
			(loaded.solution && drafts.solution !== baseline.solution)
	);
	const partDirty = $derived(loaded[part] && drafts[part] !== baseline[part]);
	const allLoaded = $derived(loaded.question && loaded.solution);
	const fileName = $derived(part === 'question' ? 'question.tex' : 'solution.tex');
	const lineCount = $derived(draft.split('\n').length);

	let saveState = $state('saved'); // saved | dirty | saving
	let saveError = $state('');
	let saveSeq = 0;
	let allowNav = false;
	let toast = $state('');
	let toastTimer = null;
	let segments = $state([]);
	let previewStale = $state(false);
	let previewError = $state('');
	let previewTimer = null;
	let previewSeq = 0;
	let mobileTab = $state('edit'); // edit | preview (narrow screens only)
	let pendingNav = $state(null); // { type: 'part'|'back'|'nav', value?, to? }
	let figOpen = $state(false);
	let figuresError = $state('');

	function showToast(msg) {
		toast = msg;
		clearTimeout(toastTimer);
		toastTimer = setTimeout(() => (toast = ''), 3200);
	}

	async function loadPart(p) {
		try {
			const res = await api.getTex(paper, qn, p);
			baseline[p] = res.tex;
			drafts[p] = res.tex;
			shas[p] = res.sha256;
			loaded[p] = true;
			if (p === part) {
				previewStale = true;
				queuePreview();
			}
		} catch (e) {
			loadError = `Could not load ${p}.tex: ${e.message}`;
		}
	}

	function queuePreview() {
		previewStale = true;
		previewError = '';
		clearTimeout(previewTimer);
		previewTimer = setTimeout(async () => {
			const seq = ++previewSeq;
			const text = drafts[part];
			const activePart = part;
			try {
				const res = await api.previewTex(paper, qn, { tex: text, part: activePart });
				if (seq !== previewSeq) return; // stale response
				segments = res.segments;
				previewStale = false;
			} catch (e) {
				if (seq !== previewSeq) return;
				previewStale = false;
				previewError = `Preview failed: ${e.message}`;
			}
		}, 350);
	}

	function onInput(value) {
		drafts[part] = value;
		saveState = dirty ? 'dirty' : 'saved';
		saveError = '';
		queuePreview();
	}

	function switchPart(next) {
		if (next === part) return;
		if (saveState === 'saving') {
			showToast('Saving… please wait.');
			return;
		}
		if (dirty) {
			pendingNav = { type: 'part', value: next };
			return;
		}
		part = next;
		mobileTab = 'edit';
		queuePreview();
	}

	async function saveAndSwitch(next) {
		pendingNav = null;
		const ok = await save();
		if (ok) {
			part = next;
			mobileTab = 'edit';
			queuePreview();
		} else {
			pendingNav = { type: 'part', value: next };
		}
	}

	function confirmNav() {
		if (!pendingNav) return;
		// Discard chosen edits, then follow through.
		if (pendingNav.type === 'part' || pendingNav.type === 'back') {
			drafts.question = baseline.question;
			drafts.solution = baseline.solution;
		}
		saveState = 'saved';
		saveSeq++; // invalidate any in-flight save result
		const nav = pendingNav;
		pendingNav = null;
		if (nav.type === 'part') {
			part = nav.value;
			queuePreview();
		} else if (nav.type === 'back') {
			window.location.href = backHref;
		} else {
			allowNav = true;
			goto(nav.to, { invalidateAll: false }).finally(() => (allowNav = false));
		}
	}

	async function save() {
		if (saveState === 'saving') return false;
		const seq = ++saveSeq;
		const savedPart = part;
		const savedText = drafts[part];
		saveState = 'saving';
		saveError = '';
		try {
			const res = await api.saveTex(paper, qn, {
				part: savedPart,
				tex: savedText,
				expectedSha: shas[savedPart]
			});
			if (seq !== saveSeq) return false; // superseded; ignore stale result
			// Disk now holds savedText. Advance the baseline to it; anything
			// typed since stays dirty.
			baseline[savedPart] = savedText;
			shas[savedPart] = res.sha256;
			if (savedPart === part) {
				segments = res.segments ?? segments;
				previewStale = false;
			}
			const clean = drafts[savedPart] === savedText;
			saveState = dirty ? 'dirty' : 'saved';
			try {
				dropQuestionDetail(paper, qn);
			} catch { /* cache is best-effort */ }
			showToast(
				clean ? `Saved ${savedPart}.tex.` : `Saved ${savedPart}.tex — newer edits still unsaved.`
			);
			return true;
		} catch (e) {
			if (seq !== saveSeq) return false;
			saveState = 'dirty';
			saveError = String(e.message).startsWith('409:')
				? 'Someone else saved first. Copy your draft, reload the saved file, and reapply your edits.'
				: `Save failed: ${e.message}`;
			return false;
		}
	}

	function discard() {
		drafts[part] = baseline[part];
		saveState = dirty ? 'dirty' : 'saved';
		saveError = '';
		segments = [];
		queuePreview();
		showToast('Draft reset to the saved file.');
	}

	async function copyFig(name) {
		const snippet = `\\includegraphics{figures/${name}}`;
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

	async function copyDraft() {
		try {
			await navigator.clipboard.writeText(drafts[part]);
			showToast('Draft copied — safe to reload.');
		} catch {
			showToast('Copy failed — select the editor text manually.');
		}
	}

	async function reloadSaved() {
		loaded[part] = false;
		saveError = '';
		await loadPart(part);
	}

	function goBack(e) {
		if (saveState === 'saving') {
			e.preventDefault();
			showToast('Saving… please wait.');
			return;
		}
		if (dirty) {
			e.preventDefault();
			pendingNav = { type: 'back' };
		}
	}

	function onKey(e) {
		if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
			e.preventDefault();
			if (allLoaded && dirty && saveState !== 'saving') save();
			return;
		}
		if (e.key === 'Escape') {
			if (pendingNav) pendingNav = null;
			else figOpen = false;
		}
	}

	function trapTab(e) {
		if (e.key !== 'Tab' || !dialogEl) return;
		const items = [...dialogEl.querySelectorAll('button')].filter((b) => !b.disabled);
		if (items.length === 0) return;
		const first = items[0];
		const last = items[items.length - 1];
		if (e.shiftKey && document.activeElement === first) {
			e.preventDefault();
			last.focus();
		} else if (!e.shiftKey && document.activeElement === last) {
			e.preventDefault();
			first.focus();
		}
	}

	function onWindowClick(e) {
		if (figOpen && !(e.target instanceof Element && e.target.closest('.figdrop'))) figOpen = false;
	}

	$effect(() => {
		// Warn on reload/close with unsaved edits. Chrome requires returnValue.
		const handler = (e) => {
			if (dirty || saveState === 'saving') {
				e.preventDefault();
				e.returnValue = '';
			}
		};
		window.addEventListener('beforeunload', handler);
		return () => window.removeEventListener('beforeunload', handler);
	});

	beforeNavigate((nav) => {
		if (allowNav || (!dirty && saveState !== 'saving')) return;
		nav.cancel();
		if (saveState === 'saving') {
			showToast('Saving… please wait.');
			return;
		}
		if (nav.to?.url) pendingNav = { type: 'nav', to: nav.to.url };
	});

	let dialogEl = $state(null);
	let lastFocus = null;
	$effect(() => {
		if (pendingNav && dialogEl) {
			lastFocus = document.activeElement;
			const h = dialogEl.querySelector('h2');
			h?.setAttribute('tabindex', '-1');
			h?.focus();
		} else if (!pendingNav && lastFocus?.focus) {
			lastFocus.focus();
			lastFocus = null;
		}
	});

	onMount(async () => {
		// Figures and tex parts are independent: fetch together so a slow
		// figure list never delays the editor text (errors stay per-part).
		const [figs] = await Promise.all([
			api.listFigures(paper, qn).catch((e) => {
				figuresError = `Could not load figures: ${e.message}`;
				return [];
			}),
			loadPart('question'),
			loadPart('solution')
		]);
		figures = figs;
	});
</script>

<svelte:head><title>TeX editor - Paper {paper} Q{qn} - PaperLab</title></svelte:head>
<svelte:window onkeydown={onKey} onclick={onWindowClick} />

<div class="ws">
	<header class="topbar">
		<a class="back" href={backHref} onclick={goBack}>← Back</a>
		<span class="ident pl-mono">Paper {paper} · Q{qn}</span>
		<span class="expbadge" title="Experimental workspace: TeX saves are real, everything else is read-only">Experimental</span>
		<div class="seg" role="group" aria-label="Choose file">
			<button type="button" class:active={part === 'question'} aria-pressed={part === 'question'} disabled={saveState === 'saving'} onclick={() => switchPart('question')}>Question</button>
			<button type="button" class:active={part === 'solution'} aria-pressed={part === 'solution'} disabled={saveState === 'saving'} onclick={() => switchPart('solution')}>Solution</button>
			<div class="figdrop">
				<button
					type="button"
					class:active={figOpen}
					aria-haspopup="menu"
					aria-expanded={figOpen}
					title="Copy a figure's \\includegraphics into the editor"
					onclick={() => (figOpen = !figOpen)}
				>
					<svg class="figico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/></svg>
					Copy figures
				</button>
				{#if figOpen}
					<ul class="figmenu" role="menu" aria-label="Figures in this question">
						{#if figuresError}
							<li role="none"><span class="figempty">{figuresError}</span></li>
						{:else if figures.length === 0}
							<li role="none"><span class="figempty">No figures in this question.</span></li>
						{:else}
							{#each figures as f (f.name)}
								<li role="none">
									<button
										type="button"
										role="menuitem"
										title={`Used in: ${(f.usedIn ?? []).join(', ') || 'unused'} — click to copy`}
										onclick={() => { copyFig(f.name); figOpen = false; }}
									>{f.name}</button>
								</li>
							{/each}
						{/if}
					</ul>
				{/if}
			</div>
		</div>
		<span class="status" data-state={saveState} role="status">
			{#if !allLoaded}Loading…
			{:else if saveState === 'saving'}Saving…
			{:else if dirty}Unsaved changes
			{:else}Saved{/if}
		</span>
		<div class="actions">
			<button type="button" class="pl-btn" disabled={!dirty || saveState === 'saving'} onclick={discard}>Discard</button>
			<button type="button" class="pl-btn pl-btn-primary" disabled={!dirty || saveState === 'saving'} onclick={save}>
				{saveState === 'saving' ? 'Saving…' : 'Save'}
			</button>
		</div>
	</header>

	{#if loadError}
		<p class="pl-error loaderr" role="alert">{loadError}</p>
	{/if}
	{#if saveError}
		<div class="loaderr" role="alert">
			<span class="pl-error">{saveError}</span>
			<span class="errbtns">
				<button type="button" class="pl-btn" onclick={copyDraft}>Copy my draft</button>
				<button type="button" class="pl-btn" onclick={reloadSaved}>Reload saved file</button>
			</span>
		</div>
	{/if}

	<nav class="mobtabs" role="tablist" aria-label="Workspace view">
		<button type="button" role="tab" aria-selected={mobileTab === 'edit'} class:active={mobileTab === 'edit'} onclick={() => (mobileTab = 'edit')}>Editor</button>
		<button type="button" role="tab" aria-selected={mobileTab === 'preview'} class:active={mobileTab === 'preview'} onclick={() => (mobileTab = 'preview')}>
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
				aria-label={`Edit ${fileName}`}
				disabled={!allLoaded || saveState === 'saving'}
				bind:value={drafts[part]}
				oninput={(e) => onInput(e.currentTarget.value)}
			></textarea>
		</section>

		<section class="pane previewpane" class:active={mobileTab === 'preview'} aria-label="Preview">
			<div class="panehead">
				<span>Preview</span>
				<span class="pl-sub prevstate">
					{#if previewStale}Updating…
					{:else if previewError}<span role="status">{previewError}</span> <button type="button" class="retrybtn" onclick={queuePreview}>Retry</button>
					{:else}Live render · reader styles{/if}
				</span>
			</div>
			<div class="paper">
				{#if !allLoaded}
					<div class="skel" aria-hidden="true"></div>
					<div class="skel short" aria-hidden="true"></div>
					<div class="skel" aria-hidden="true"></div>
				{:else}
					<Segments {segments} zoomable />
				{/if}
			</div>
		</section>
	</div>

	{#if toast}
		<p class="toast" role="status">{toast}</p>
	{/if}

	{#if pendingNav}
		<div class="overlay" role="dialog" aria-modal="true" aria-label="Unsaved changes" onkeydown={trapTab}>
			<div class="dialog" bind:this={dialogEl}>
				{#if pendingNav.type === 'part'}
					<h2>Switch file with unsaved edits?</h2>
					<p class="pl-sub">Your {part}.tex edits are not saved yet.</p>
					<div class="dialogrow">
						<button type="button" class="pl-btn" onclick={() => (pendingNav = null)}>Keep editing</button>
						<button type="button" class="pl-btn" onclick={confirmNav}>Discard & switch</button>
						<button type="button" class="pl-btn pl-btn-primary" onclick={() => saveAndSwitch(pendingNav.value)}>Save & switch</button>
					</div>
				{:else}
					<h2>Leave with unsaved edits?</h2>
					<p class="pl-sub">Your edits are not saved yet. Leaving now loses the draft text.</p>
					<div class="dialogrow">
						<button type="button" class="pl-btn pl-btn-primary" onclick={() => (pendingNav = null)}>Keep editing</button>
						<button type="button" class="pl-btn" onclick={confirmNav}>Discard changes</button>
					</div>
				{/if}
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
	.expbadge {
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
	.seg {
		display: inline-flex;
		background: var(--pl-raised);
		border-radius: var(--pl-radius-pill);
		padding: 3px;
		gap: 2px;
	}
	.seg > button,
	.figdrop > button {
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
	.seg > button.active,
	.figdrop > button.active {
		background: var(--pl-surface);
		color: var(--pl-ink);
		box-shadow: var(--pl-shadow-sm);
	}
	.figdrop {
		position: relative;
		display: inline-flex;
	}
	.figdrop > button {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.figico {
		width: 13px;
		height: 13px;
	}
	.figmenu {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 40;
		list-style: none;
		margin: 0;
		padding: 4px;
		min-width: 220px;
		max-width: min(320px, 80vw);
		max-height: 50dvh;
		overflow-y: auto;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		box-shadow: var(--pl-shadow-md);
	}
	.figmenu button {
		display: block;
		width: 100%;
		border: none;
		background: none;
		text-align: left;
		padding: 8px 10px;
		min-height: 0;
		font-size: 0.8rem;
		font-family: var(--pl-font-mono);
		color: var(--pl-ink);
		border-radius: var(--pl-radius-sm);
		cursor: pointer;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.figmenu button:hover {
		background: var(--pl-raised);
	}
	.figempty {
		display: block;
		padding: 8px 10px;
		font-size: 0.8rem;
		color: var(--pl-ink-soft);
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
	.loaderr {
		margin: 12px 16px 0;
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}
	.errbtns {
		display: inline-flex;
		gap: 8px;
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
	.seg > button:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.panehead .prevstate {
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}
	.retrybtn {
		border: 1px solid var(--pl-line);
		background: var(--pl-surface);
		border-radius: var(--pl-radius-sm);
		padding: 2px 10px;
		min-height: 0;
		font-size: 0.78rem;
		font-weight: 600;
		cursor: pointer;
	}
	.skel {
		height: 1em;
		border-radius: 4px;
		background: var(--pl-raised);
		margin: 0.9em 0;
	}
	.skel.short {
		width: 55%;
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
	.editor:disabled {
		opacity: 0.6;
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
