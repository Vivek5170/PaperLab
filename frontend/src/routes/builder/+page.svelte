<script>
	import { browser } from '$app/environment';
import { cartStore } from '$lib/carts.js';
	import {
		builderStore, builder, docOrder, numbering, blockTotal, builderCorrupt, parsedKeys
	} from '$lib/builder.js';
	import { sectionAccepts } from '$lib/builderModel.js';
	import BuilderBlock from '$lib/components/BuilderBlock.svelte';
	import QuestionSheetPreview from '$lib/components/QuestionSheetPreview.svelte';
	import AnswerSheetPreview from '$lib/components/AnswerSheetPreview.svelte';

	const draft = $derived($builderStore);
	const order = $derived($docOrder);
	const num = $derived($numbering);
	const nBlocks = $derived($blockTotal);

	let cartId = $state('');
	let importStatus = $state(null); // {added, skipped, cartName, dupes} | {error} | null
	let confirmNew = $state(false);
	let previewMode = $state('questions'); // questions | answers
	let mobileTab = $state('edit'); // edit | preview (narrow screens only)
	let undo = $state(null);
	let undoTimer = null;
	let collapsed = $state({});
	let dragBid = $state(null);
	let splitPct = $state(browser ? Number(sessionStorage.getItem('pl-split-v1')) || 38 : 38);
	let figBoxed = $state(browser ? localStorage.getItem('pl-figbox-v1') === '1' : false);
	let sheetFont = $state(
		browser && ['paperlab', 'times', 'kokila', 'arial', 'cambria'].includes(localStorage.getItem('pl-sheetfont-v1'))
			? localStorage.getItem('pl-sheetfont-v1')
			: 'paperlab'
	);
	let figScale = $state(
		browser && Number(localStorage.getItem('pl-figscale-v1')) >= 40 && Number(localStorage.getItem('pl-figscale-v1')) <= 120
			? Number(localStorage.getItem('pl-figscale-v1'))
			: 80
	);

	function toggleSection(id) {
		collapsed[id] = !collapsed[id];
	}

	$effect(() => {
		try {
			localStorage.setItem('pl-figbox-v1', figBoxed ? '1' : '0');
			localStorage.setItem('pl-sheetfont-v1', sheetFont);
			localStorage.setItem('pl-figscale-v1', String(figScale));
		} catch { /* private mode: prefs last the session */ }
	});
	function clampSplit(pct, w) {
		const minL = Math.min(50, (280 / Math.max(w, 1)) * 100);
		return Math.max(minL, Math.min(62, pct));
	}
	function persistSplit() {
		try {
			sessionStorage.setItem('pl-split-v1', String(Math.round(splitPct)));
		} catch { /* private mode: session-only anyway */ }
	}
	function startSplit(e) {
		e.preventDefault();
		const el = e.currentTarget;
		try {
			el.setPointerCapture?.(e.pointerId);
		} catch { /* ignore */ }
		const move = (ev) => {
			const host = el.closest('.workspace');
			const r = host?.getBoundingClientRect();
			if (!r || r.width <= 0) return;
			splitPct = clampSplit(((ev.clientX - r.left) / r.width) * 100, r.width);
		};
		const up = () => {
			persistSplit();
			window.removeEventListener('pointermove', move);
			window.removeEventListener('pointerup', up);
		};
		window.addEventListener('pointermove', move);
		window.addEventListener('pointerup', up);
	}
	function splitKeys(e) {
		if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
		e.preventDefault();
		const w = e.currentTarget.closest('.workspace')?.getBoundingClientRect()?.width ?? 1200;
		splitPct = clampSplit(splitPct + (e.key === 'ArrowRight' ? 2 : -2), w);
		persistSplit();
	}

	const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

	$effect(() => {
		if (!cartId && $cartStore.carts.length > 0) cartId = $cartStore.activeId ?? $cartStore.carts[0].id;
	});

	const activeCart = $derived($cartStore.carts.find((c) => c.id === cartId) ?? null);
	const empty = $derived(nBlocks === 0);

	function doImport(allowDupes) {
		if (!activeCart) return;
		const r = builder.importFromCart(activeCart.items, { allowDupes });
		importStatus = { added: r.added.length, skipped: r.skipped.length, cartName: activeCart.name, dupes: !allowDupes };
	}

	function removeWithUndo(bid, label) {
		const snap = builder.removeBlock(bid);
		if (!snap) return;
		showUndo({ kind: 'remove', label: `Removed ${label}`, snap });
	}

	function captureOrder() {
		return {
			sectionIds: draft.sections.map((s) => s.id),
			blocks: Object.fromEntries(draft.sections.map((s) => [s.id, [...s.blockIds]]))
		};
	}

	function showUndo(entry) {
		undo = entry;
		clearTimeout(undoTimer);
		undoTimer = setTimeout(() => (undo = null), 12000);
	}

	function reorderWithUndo(label, fn) {
		const order = captureOrder();
		const changed = fn();
		if (changed !== false) showUndo({ kind: 'order', label: `Moved ${label}`, order });
	}

	function blockLabel(bid) {
		const b = draft.blocks[bid];
		if (!b) return 'question';
		return `${(num.byBlock[bid] ?? []).map((n) => `Q${n}`).join('–')} (Paper ${b.paperId} · ${b.number})`;
	}

	function stepWithUndo(bid, dir) {
		reorderWithUndo(blockLabel(bid), () => builder.moveBlock(bid, dir));
	}

	function doUndo() {
		if (!undo) return;
		if (undo.kind === 'remove') {
			const fallback = draft.sections.find((s) => sectionAccepts(s, undo.snap.block))?.id
				?? draft.sections[0]?.id ?? null;
			const ok = builder.restoreBlock(undo.snap, fallback);
			undo = null;
			clearTimeout(undoTimer);
			if (!ok) importStatus = { added: 0, skipped: 0, cartName: '', error: 'Could not undo — the section is gone. Re-import the question from its cart.' };
		} else {
			builder.restoreSectionOrder(undo.order);
			undo = null;
			clearTimeout(undoTimer);
		}
	}

	function sectionOf(bid) {
		return draft.sections.find((s) => s.blockIds.includes(bid)) ?? null;
	}

	function canDropSection(sectionId) {
		if (!dragBid) return false;
		const dst = draft.sections.find((s) => s.id === sectionId);
		if (!dst) return false;
		if (dst.blockIds.includes(dragBid)) return true;
		const b = draft.blocks[dragBid];
		return !!b && sectionAccepts(dst, b);
	}

	function dropOnRow(refBid, pos, refSectionId) {
		const from = dragBid;
		dragBid = null;
		if (!from || from === refBid) return;
		const dst = draft.sections.find((s) => s.id === refSectionId);
		const src = sectionOf(from);
		if (!dst || !src) return;
		const label = blockLabel(from);
		if (src.id === dst.id) {
			const ids = dst.blockIds.filter((id) => id !== from);
			let idx = ids.indexOf(refBid) + (pos === 'after' ? 1 : 0);
			if (idx < 0 || refBid === undefined) idx = ids.length;
			reorderWithUndo(label, () => builder.moveBlockTo(from, idx));
		} else {
			const b = draft.blocks[from];
			if (!b || !sectionAccepts(dst, b)) return;
			const ids = dst.blockIds.filter((id) => id !== from);
			let idx = ids.indexOf(refBid) + (pos === 'after' ? 1 : 0);
			if (idx < 0) idx = ids.length;
			reorderWithUndo(label, () => builder.moveBlockToSectionAt(from, dst.id, idx).moved);
		}
	}

	function dropOnSectionEnd(sectionId) {
		const from = dragBid;
		dragBid = null;
		if (!from) return;
		const dst = draft.sections.find((s) => s.id === sectionId);
		if (!dst || !canDropSection(sectionId)) return;
		reorderWithUndo(blockLabel(from), () => {
			if (dst.blockIds.includes(from)) return builder.moveBlockTo(from, dst.blockIds.length);
			return builder.moveBlockToSectionAt(from, dst.id, dst.blockIds.length).moved;
		});
	}
</script>

<svelte:head><title>Paper Builder - PaperLab</title></svelte:head>

<div class="page">
	<header class="topbar">
		<span class="ident">Paper builder</span>
		<div class="seg" role="group" aria-label="Preview mode">
			<button type="button" class:active={previewMode === 'questions'} aria-pressed={previewMode === 'questions'} onclick={() => (previewMode = 'questions')}>Question Sheet</button>
			<button type="button" class:active={previewMode === 'answers'} aria-pressed={previewMode === 'answers'} onclick={() => (previewMode = 'answers')}>Answer Sheet</button>
		</div>
		<span class="docstatus" role="status">{empty ? 'Empty draft' : `${draft.mode === 'paper' ? 'Paper' : 'Assignment'} · ${nBlocks} blocks · ${num.total} numbers`}</span>
		{#if undo}
			<span class="undobar" role="status">
				{undo.label}.
				<button type="button" class="mini" onclick={doUndo}>Undo</button>
			</span>
		{/if}
		<div class="actions">
			<button
				type="button"
				role="switch"
				aria-checked={figBoxed}
				class="frameswitch"
				class:on={figBoxed}
				title={figBoxed ? 'Hide boxes around figures' : 'Show boxes around figures'}
				onclick={() => (figBoxed = !figBoxed)}
			>
				<span>Frames</span>
				<span class="track" aria-hidden="true"><span class="knob"></span></span>
			</button>
			<select
				class="fontsel"
				bind:value={sheetFont}
				aria-label="Sheet body font"
				title="Sheet body font: Inter, Times (Chaitanya), Kokila (Allen), Arial (FITJEE), Cambria"
			>
				<option value="paperlab">Inter</option>
				<option value="times">Times (Chaitanya)</option>
				<option value="kokila">Kokila (Allen)</option>
				<option value="arial">Arial (FITJEE)</option>
				<option value="cambria">Cambria</option>
			</select>
			<button type="button" class="pl-btn" onclick={() => (confirmNew = true)}>New</button>
			<button type="button" class="pl-btn pl-btn-primary" onclick={() => window.print()} title="Print or save as PDF (A4, exactly as previewed)">Print / PDF</button>
		</div>
	</header>

	{#if $builderCorrupt}
		<div class="pl-error corrupt" role="alert">
			<strong>Saved builder draft was corrupt.</strong>
			<button type="button" class="pl-btn" onclick={() => builderCorrupt.set(false)}>Dismiss</button>
		</div>
	{/if}
	{#if confirmNew}
		<div class="confirmstrip" role="alert">
			<span>Discard this draft and start empty?</span>
			<span class="errbtns">
				<button type="button" class="pl-btn pl-btn-primary" onclick={() => { builder.newDraft(draft.mode); confirmNew = false; }}>Discard draft</button>
				<button type="button" class="pl-btn" onclick={() => (confirmNew = false)}>Keep</button>
			</span>
		</div>
	{/if}

	<nav class="mobtabs" role="tablist" aria-label="Builder view">
		<button type="button" role="tab" aria-selected={mobileTab === 'edit'} class:active={mobileTab === 'edit'} onclick={() => (mobileTab = 'edit')}>Editor</button>
		<button type="button" role="tab" aria-selected={mobileTab === 'preview'} class:active={mobileTab === 'preview'} onclick={() => (mobileTab = 'preview')}>Preview</button>
	</nav>

	<div class="workspace" data-view={mobileTab} style:--lw={`${splitPct}%`}>
		<!-- ================= LEFT: editor ================= -->
		<div class="editor">
			<div class="panehead">
				<span>Draft</span>
				<span class="pl-sub">Auto-saved in this browser</span>
			</div>
			<div class="panebody">
			<div class="panel pl-card">
				<label class="title">
					<span class="pl-sub">Title</span>
					<input
						type="text" value={draft.title} placeholder="e.g. JEE Advanced 2023 Mock 1"
						maxlength="120" aria-label="Draft title"
						oninput={(e) => builder.setTitle(e.currentTarget.value)}
					/>
				</label>
				<div class="moderow" role="radiogroup" aria-label="Draft mode">
					<label class:off={!empty && draft.mode !== 'paper'}>
						<input type="radio" name="mode" checked={draft.mode === 'paper'} disabled={!empty} onchange={() => builder.newDraft('paper')} />
						Paper <span class="pl-sub">(sections)</span>
					</label>
					<label class:off={!empty && draft.mode !== 'assignment'}>
						<input type="radio" name="mode" checked={draft.mode === 'assignment'} disabled={!empty} onchange={() => builder.newDraft('assignment')} />
						Assignment <span class="pl-sub">(flat)</span>
					</label>
				</div>
				<hr class="seprule" />
				<div class="importlabel">
					<span>Import from cart</span>
				</div>
				<div class="importrow">
					<select bind:value={cartId} aria-label="Source cart">
						{#each $cartStore.carts as c (c.id)}
							<option value={c.id}>{c.name} · {c.items.length}</option>
						{/each}
					</select>
					<button type="button" class="pl-btn" disabled={!activeCart || activeCart.items.length === 0} onclick={() => doImport(false)}>
						Import
					</button>
				</div>
				{#if draft.mode === 'paper'}
					<p class="pl-sub hint">Imports group automatically — one section per question type.</p>
				{/if}
				{#if importStatus}
					<div class="status" role="status">
						{#if importStatus.error}
							<span>{importStatus.error}</span>
						{:else if importStatus.added > 0 && importStatus.skipped === 0}
							<span>Imported <strong>{importStatus.added}</strong> from {importStatus.cartName}.</span>
						{:else if importStatus.added > 0}
							<span>Added <strong>{importStatus.added}</strong> · {importStatus.skipped} already in.</span>
							{#if importStatus.dupes}
								<button type="button" class="mini" onclick={() => doImport(true)}>Import dupes too</button>
							{/if}
						{:else if importStatus.skipped > 0}
							<span>All {importStatus.skipped} already in — nothing new.</span>
							{#if importStatus.dupes}
								<button type="button" class="mini" onclick={() => doImport(true)}>Import anyway</button>
							{/if}
						{/if}
					</div>
				{/if}
			</div>

			<div class="panel pl-card">
				<div class="sechead">
					<h2>{draft.mode === 'paper' ? 'Sections' : 'Questions'} · {nBlocks} → {num.total} nos.</h2>
				</div>

				{#if num.warnings.length > 0}
					<ul class="warns">
						{#each num.warnings as w (w.blockId)}
							<li role="note">{w.warning}</li>
						{/each}
					</ul>
				{/if}

				{#if empty && draft.sections.length === 0}
					<p class="pl-sub">No questions yet. Import a cart above — the draft stays independent of the cart afterwards.</p>
				{:else if draft.mode === 'assignment'}
					{@const s = draft.sections[0]}
					<div
						class="blocks"
						ondragover={(e) => { if (e.currentTarget === e.target && canDropSection(s.id)) { e.preventDefault(); e.currentTarget.classList.add('dropend'); } }}
						ondragleave={(e) => e.currentTarget.classList.remove('dropend')}
						ondrop={(e) => { e.preventDefault(); e.currentTarget.classList.remove('dropend'); dropOnSectionEnd(s.id); }}
					>
						{#each s.blockIds as bid (bid)}
							{@const b = draft.blocks[bid]}
							{#if b}
								<BuilderBlock
									block={b}
									numbers={num.byBlock[bid] ?? []}
									showType
									onUp={() => stepWithUndo(bid, -1)}
									onDown={() => stepWithUndo(bid, 1)}
									onRemove={() => removeWithUndo(bid, `Q${(num.byBlock[bid] ?? []).join(', Q')} (Paper ${b.paperId} · ${b.number})`)}
									onDragStart={(id) => (dragBid = id)}
									canDrop={(refBid) => refBid !== dragBid}
									onDropRow={(refBid, pos) => dropOnRow(refBid, pos, s.id)}
								/>
							{/if}
						{:else}
							<p class="pl-sub">Empty — import a cart to fill it.</p>
						{/each}
					</div>
				{:else}
					{#each draft.sections as s, si (s.id)}
						{@const secLetter = LETTERS[si] ?? `X${si + 1}`}
					{@const secNums = s.blockIds.flatMap((bid) => num.byBlock[bid] ?? [])}
					{@const secRange = secNums.length > 1 ? `Q${secNums[0]}–Q${secNums[secNums.length - 1]}` : secNums.length === 1 ? `Q${secNums[0]}` : 'empty'}
					<section class="section" aria-label={`Section ${secLetter}`}>
						<div class="stitle">
							<button type="button" class="twisty" aria-expanded={!collapsed[s.id]} aria-label={`${collapsed[s.id] ? 'Expand' : 'Collapse'} section ${secLetter}`} title={collapsed[s.id] ? 'Expand' : 'Collapse'} onclick={() => toggleSection(s.id)}>
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={collapsed[s.id] ? 'm9 6 6 6-6 6' : 'm6 9 6 6 6-6'} /></svg>
							</button>
							<span class="secletter" title="Auto section">{secLetter}</span>
							{#if s.atype === 'passage'}
								<span class="atype passage" title="Structural group: passages stay whole, children keep their own types">PASSAGES</span>
							{:else}
								<span class="atype" title={`Auto-grouped ${s.atype}`}>{s.atype.toUpperCase()}</span>
							{/if}
							<span class="pl-sub count">{secNums.length} q · {secRange}</span>
							{#if draft.sections.length > 1}
								<span class="secops" role="group" aria-label={`Reorder section ${secLetter}`}>
									<button type="button" disabled={si === 0} onclick={() => reorderWithUndo(`Section ${secLetter}`, () => builder.moveSection(si, si - 1))} title="Move section up" aria-label={`Move section ${secLetter} up`}>
										<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg>
									</button>
									<button type="button" disabled={si === draft.sections.length - 1} onclick={() => reorderWithUndo(`Section ${secLetter}`, () => builder.moveSection(si, si + 1))} title="Move section down" aria-label={`Move section ${secLetter} down`}>
										<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14m-6-6 6 6 6-6"/></svg>
									</button>
								</span>
							{/if}
						</div>
						{#if !collapsed[s.id]}
							{#if s.atype === 'passage' && s.blockIds.length > 0}
								<p class="pl-sub passage-note">Passages stay whole; children keep their own types and numbers.</p>
							{/if}
							<div
								class="blocks"
								ondragover={(e) => { if (e.currentTarget === e.target && canDropSection(s.id)) { e.preventDefault(); e.currentTarget.classList.add('dropend'); } }}
								ondragleave={(e) => e.currentTarget.classList.remove('dropend')}
								ondrop={(e) => { e.preventDefault(); e.currentTarget.classList.remove('dropend'); dropOnSectionEnd(s.id); }}
							>
								{#each s.blockIds as bid (bid)}
									{@const b = draft.blocks[bid]}
									{#if b}
										<BuilderBlock
											block={b}
											numbers={num.byBlock[bid] ?? []}
											showType={false}
											onUp={() => stepWithUndo(bid, -1)}
											onDown={() => stepWithUndo(bid, 1)}
											onRemove={() => removeWithUndo(bid, `${(num.byBlock[bid] ?? []).map((n) => `Q${n}`).join('–')} (Paper ${b.paperId} · ${b.number})`)}
											onDragStart={(id) => (dragBid = id)}
											canDrop={(refBid) => refBid !== dragBid && canDropSection(s.id)}
											onDropRow={(refBid, pos) => dropOnRow(refBid, pos, s.id)}
										/>
									{/if}
								{:else}
									<p class="pl-sub">Empty section — excluded from numbering until it holds a block. Import a cart to fill it.</p>
								{/each}
							</div>
						{/if}
						</section>
					{/each}
				{/if}
			</div>
			</div>
		</div>

		<div
			class="splitter"
			role="separator"
			aria-orientation="vertical"
			aria-label="Resize editor and preview panels"
			tabindex="0"
			title="Drag to resize panels"
			onpointerdown={startSplit}
			onkeydown={splitKeys}
		></div>

		<!-- ================= RIGHT: document ================= -->
		<div class="previewcol">
			<div class="panehead">
				<span>Preview</span>
				<span class="previewmeta">
					<label class="figctl" title="Diagram size — pages reflow live, print matches">
						Fig
						<input
							type="range" min="40" max="120" step="5"
							bind:value={figScale} aria-label="Figure size percent"
						/>
						<span class="pl-sub">{figScale}%</span>
					</label>
					<span class="pl-sub">Live A4 · print exact</span>
				</span>
			</div>
			<div class="previewscroll">
				{#if previewMode === 'questions'}
					<QuestionSheetPreview title={draft.title} ordered={order} numbering={num} sections={draft.sections} mode={draft.mode} bare={!figBoxed} font={sheetFont} figScale={figScale} />
				{:else}
					<AnswerSheetPreview
						title={draft.title} numbering={num} blocks={draft.blocks}
						overrides={draft.keyOverride} parsed={$parsedKeys} ordered={order} bare={!figBoxed} font={sheetFont} figScale={figScale}
						onOverride={(bid, i, t) => builder.setOverride(bid, i, t)}
					/>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.page {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	/* Slim single-row chrome, mirrors the TeX edit page. */
	.topbar {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		padding: 8px 16px;
		background: var(--pl-surface);
		border-bottom: 1px solid var(--pl-line);
	}
	.ident {
		font-size: 0.9rem;
		font-weight: 700;
		white-space: nowrap;
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
		padding: 5px 14px;
		min-height: 0;
		font-size: 0.8rem;
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
	.docstatus {
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
		white-space: nowrap;
	}
	.actions {
		margin-left: auto;
		display: flex;
		gap: 8px;
		align-items: center;
	}
	/* Compact 2-3 chrome buttons: beat the global 44px touch target. */
	.topbar .pl-btn,
	.confirmstrip .pl-btn,
	.corrupt .pl-btn {
		min-height: 0;
		padding: 6px 14px;
		font-size: 0.8rem;
	}
	.undobar {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		font-size: 0.78rem;
	}
	.corrupt {
		margin: 10px 16px 0;
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}
	.confirmstrip {
		margin: 10px 16px 0;
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		font-size: 0.82rem;
	}
	.errbtns {
		display: inline-flex;
		gap: 8px;
	}
	.mobtabs {
		display: none;
	}
	/* Two panes, no gaps: divider border only, like the edit page. */
	.workspace {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(280px, var(--lw, 38%)) 8px minmax(0, 1fr);
	}
	.splitter {
		position: relative;
		cursor: col-resize;
		min-width: 0;
		border-radius: 4px;
	}
	.splitter::after {
		content: '';
		position: absolute;
		inset: 0 3px;
		border-radius: 2px;
		background: transparent;
		transition: background 120ms;
	}
	.splitter:hover::after,
	.splitter:active::after,
	.splitter:focus-visible::after {
		background: var(--pl-seal);
		opacity: 0.45;
	}
	.splitter:focus-visible {
		outline: 2px solid var(--pl-focus);
		outline-offset: -2px;
	}
	.editor {
		min-height: 0;
		display: flex;
		flex-direction: column;
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
		flex-shrink: 0;
		position: sticky;
		top: 0;
		z-index: 5;
		background: var(--pl-paper);
	}
	.panehead .pl-sub {
		font-weight: 400;
	}
	.previewmeta {
		display: inline-flex;
		align-items: center;
		gap: 12px;
	}
	.figctl {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
	}
	.figctl input[type='range'] {
		width: 90px;
		min-height: 0;
		padding: 0;
		accent-color: var(--pl-seal);
		cursor: pointer;
	}
	.panebody {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 4px 16px 24px;
		display: flex;
		flex-direction: column;
	}
	.panel {
		margin-bottom: 10px;
		padding: 12px;
		flex-shrink: 0;
	}
	.panebody .panel:last-child {
		margin-bottom: 0;
	}
	.panel h2 {
		margin: 0 0 8px;
		font-size: 0.95rem;
	}
	.title {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-bottom: 10px;
	}
	.moderow {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 16px;
		align-items: center;
	}
	.moderow label {
		display: flex;
		gap: 8px;
		align-items: center;
		font-weight: 600;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.moderow label.off {
		opacity: 0.55;
		cursor: default;
	}
	.moderow input[type='radio'] {
		min-height: 0;
		width: 16px;
		height: 16px;
		accent-color: var(--pl-seal);
	}
	.seprule {
		border: none;
		border-top: 1px dashed var(--pl-line);
		margin: 10px 0;
	}
	.importlabel {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
		font-weight: 600;
		font-size: 0.85rem;
		margin-bottom: 6px;
	}
	.importrow {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
	}
	.importrow select {
		max-width: 100%;
		flex: 1;
		min-width: 140px;
	}
	.importrow .pl-btn {
		min-height: 0;
		padding: 7px 14px;
		font-size: 0.8rem;
	}
	.hint {
		margin: 8px 0 0;
	}
	.status {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px 12px;
		margin: 10px 0 0;
		padding: 8px 12px;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		font-size: 0.82rem;
	}
	.status strong {
		font-size: 0.9rem;
	}
	.sechead {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 10px;
	}
	.sechead h2 {
		margin: 0;
	}
	.warns {
		margin: 0 0 10px;
		padding: 0;
		list-style: none;
	}
	.warns li {
		font-size: 0.8rem;
		color: var(--pl-ochre);
		background: var(--pl-ochre-soft);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		padding: 6px 10px;
		margin-bottom: 6px;
	}
	.section {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		padding: 10px;
		margin-bottom: 10px;
		background: var(--pl-paper);
		scroll-margin-top: 12px;
	}
	.stitle {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		margin-bottom: 8px;
	}
	.twisty {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		min-height: 0;
		border: 1px solid transparent;
		border-radius: 6px;
		background: none;
		color: var(--pl-ink-soft);
		cursor: pointer;
		padding: 0;
		flex-shrink: 0;
	}
	.twisty:hover {
		border-color: var(--pl-line);
		background: var(--pl-raised);
		color: var(--pl-ink);
	}
	.twisty svg {
		width: 14px;
		height: 14px;
	}
	.secops {
		margin-left: auto;
		display: inline-flex;
		gap: 2px;
	}
	.secops button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		min-height: 0;
		border: 1px solid transparent;
		border-radius: 6px;
		background: none;
		color: var(--pl-ink-soft);
		cursor: pointer;
		padding: 0;
	}
	.secops button:hover:not(:disabled) {
		border-color: var(--pl-line);
		background: var(--pl-raised);
		color: var(--pl-ink);
	}
	.secops button:disabled {
		opacity: 0.3;
		cursor: default;
	}
	.secops svg {
		width: 13px;
		height: 13px;
	}
	.secletter {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 26px;
		height: 26px;
		border-radius: 50%;
		background: var(--pl-seal);
		color: #fff;
		font-weight: 700;
		font-size: 0.8rem;
		flex-shrink: 0;
	}
	.atype {
		font-size: 0.7rem;
		font-weight: 700;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		padding: 2px 8px;
	}
	.atype.passage {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.count {
		font-size: 0.75rem;
	}
	.passage-note {
		margin: -2px 0 8px;
		font-size: 0.76rem;
	}
	.mini {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		background: none;
		min-height: 0;
		padding: 5px 12px;
		font-size: 0.76rem;
		font-weight: 600;
		color: var(--pl-ink);
		cursor: pointer;
		white-space: nowrap;
	}
	.mini:hover:not(:disabled) {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.mini:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.fontsel {
		min-height: 0;
		font-size: 0.78rem;
		font-weight: 600;
		padding: 4px 6px;
		border-radius: 6px;
		border: 1px solid var(--pl-line);
		background: var(--pl-surface);
		color: var(--pl-ink);
		max-width: 132px;
		cursor: pointer;
	}
	.frameswitch {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		background: none;
		border: none;
		padding: 4px 2px;
		min-height: 0;
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--pl-ink-soft);
		cursor: pointer;
		white-space: nowrap;
	}
	.frameswitch .track {
		width: 34px;
		height: 20px;
		flex-shrink: 0;
		border-radius: 999px;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		position: relative;
		transition: background 120ms, border-color 120ms;
	}
	.frameswitch .knob {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		transition: left 120ms;
	}
	.frameswitch.on {
		color: var(--pl-ink);
	}
	.frameswitch.on .track {
		background: var(--pl-seal);
		border-color: var(--pl-seal);
	}
	.frameswitch.on .knob {
		left: 16px;
		background: #fff;
		border-color: #fff;
	}
	.frameswitch:focus-visible {
		outline: 2px solid var(--pl-focus);
		outline-offset: 2px;
		border-radius: 6px;
	}
	.blocks {
		display: flex;
		flex-direction: column;
		gap: 0;
	}
	.blocks .qrow {
		border-bottom: 1px solid var(--pl-line);
	}
	.blocks .qrow:last-of-type {
		border-bottom: none;
	}
	.blocks.dropend {
		outline: 2px dashed var(--pl-seal);
		outline-offset: -2px;
		border-radius: 6px;
		min-height: 40px;
	}
	/* Right: document pane. The sheet inside keeps readable width. */
	.previewcol {
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.previewscroll {
		overflow-y: auto;
		min-height: 0;
		flex: 1;
		padding: 4px 16px 32px;
	}
	@media print {
		.page {
			height: auto;
			overflow: visible;
		}
		.topbar, .mobtabs, .undobar, .corrupt, .confirmstrip, .editor, .panehead, .splitter {
			display: none;
		}
		.workspace {
			display: block;
		}
		.previewcol {
			max-height: none;
		}
		.previewscroll {
			overflow: visible;
			padding: 0;
		}
	}
	@media (max-width: 900px) {
		.page {
			height: auto;
			min-height: 0;
			overflow: visible;
		}
		.mobtabs {
			display: inline-flex;
			gap: 2px;
			background: var(--pl-raised);
			border: 1px solid var(--pl-line);
			border-radius: var(--pl-radius-pill);
			padding: 3px;
			margin: 10px 16px 0;
			width: max-content;
		}
		.mobtabs button {
			border: none;
			background: none;
			border-radius: var(--pl-radius-pill);
			padding: 6px 16px;
			min-height: 0;
			font-size: 0.8rem;
			font-weight: 600;
			color: var(--pl-ink-soft);
			cursor: pointer;
		}
		.mobtabs button.active {
			background: var(--pl-surface);
			color: var(--pl-ink);
			box-shadow: var(--pl-shadow-sm);
		}
		.workspace {
			grid-template-columns: 1fr;
			flex: none;
		}
		.splitter {
			display: none;
		}
		.workspace[data-view='edit'] .previewcol,
		.workspace[data-view='preview'] .editor {
			display: none;
		}
		.editor {
			border-right: none;
		}
		.panebody,
		.previewscroll {
			overflow: visible;
		}
	}
</style>
