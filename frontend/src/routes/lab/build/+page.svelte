<script>
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
	let undoSnap = $state(null);
	let undoLabel = $state('');
	let undoTimer = null;

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
		undoSnap = snap;
		undoLabel = label;
		clearTimeout(undoTimer);
		undoTimer = setTimeout(() => (undoSnap = null), 12000);
	}

	function undoRemove() {
		if (!undoSnap) return;
		const fallback = draft.sections.find((s) => sectionAccepts(s, undoSnap.block))?.id
			?? draft.sections[0]?.id ?? null;
		const ok = builder.restoreBlock(undoSnap, fallback);
		undoSnap = null;
		clearTimeout(undoTimer);
		if (!ok) importStatus = { added: 0, skipped: 0, cartName: '', error: 'Could not undo — the section is gone. Re-import the question from its cart.' };
	}
</script>

<svelte:head><title>Paper Builder - PaperLab</title></svelte:head>

<div class="page">
	<header class="topbar">
		<a class="back" href="/cart">← Back</a>
		<span class="ident">Paper builder</span>
		<div class="seg" role="group" aria-label="Preview mode">
			<button type="button" class:active={previewMode === 'questions'} aria-pressed={previewMode === 'questions'} onclick={() => (previewMode = 'questions')}>Question Sheet</button>
			<button type="button" class:active={previewMode === 'answers'} aria-pressed={previewMode === 'answers'} onclick={() => (previewMode = 'answers')}>Answer Sheet</button>
		</div>
		<span class="docstatus" role="status">{empty ? 'Empty draft' : `${draft.mode === 'paper' ? 'Paper' : 'Assignment'} · ${nBlocks} blocks · ${num.total} numbers`}</span>
		{#if undoSnap}
			<span class="undobar" role="status">
				Removed {undoLabel}.
				<button type="button" class="mini" onclick={undoRemove}>Undo</button>
			</span>
		{/if}
		<div class="actions">
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

	<div class="workspace" data-view={mobileTab}>
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

			</div>

			<div class="panel pl-card">
				<h2>Import from cart</h2>
				<div class="importrow">
					<select bind:value={cartId} aria-label="Source cart">
						{#each $cartStore.carts as c (c.id)}
							<option value={c.id}>{c.name} · {c.items.length}</option>
						{/each}
					</select>
					<button type="button" class="pl-btn" disabled={!activeCart || activeCart.items.length === 0} onclick={() => doImport(false)}>
						Import{activeCart ? ` ${activeCart.items.length}` : ''}
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
					<div class="blocks">
						{#each s.blockIds as bid (bid)}
							{@const b = draft.blocks[bid]}
							{#if b}
								<BuilderBlock
									block={b}
								numbers={num.byBlock[bid] ?? []}
									onUp={() => builder.moveBlock(bid, -1)}
									onDown={() => builder.moveBlock(bid, 1)}
									onRemove={() => removeWithUndo(bid, `Q${(num.byBlock[bid] ?? []).join(', Q')} (Paper ${b.paperId} · ${b.number})`)}
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
					<section class="section" aria-label={`Section ${secLetter}`}>
						<div class="stitle">
							<span class="secletter" title="Auto section">{secLetter}</span>
							{#if s.atype === 'passage'}
								<span class="atype passage" title="Structural group: passages stay whole, children keep their own types">PASSAGES</span>
							{:else}
								<span class="atype" title={`Auto-grouped ${s.atype}`}>{s.atype.toUpperCase()}</span>
							{/if}
							<span class="pl-sub count">{secNums.length} question{secNums.length === 1 ? '' : 's'}</span>
						</div>
							{#if s.atype === 'passage' && s.blockIds.length > 0}
								<p class="pl-sub passage-note">Passages stay whole; children keep their own types and numbers.</p>
							{/if}
							<div class="blocks">
								{#each s.blockIds as bid (bid)}
									{@const b = draft.blocks[bid]}
									{#if b}
										<BuilderBlock
											block={b}
											numbers={num.byBlock[bid] ?? []}
											onUp={() => builder.moveBlock(bid, -1)}
											onDown={() => builder.moveBlock(bid, 1)}
											onRemove={() => removeWithUndo(bid, `${(num.byBlock[bid] ?? []).map((n) => `Q${n}`).join('–')} (Paper ${b.paperId} · ${b.number})`)}
										/>
									{/if}
								{:else}
									<p class="pl-sub">Empty section — excluded from numbering until it holds a block.</p>
								{/each}
							</div>
						</section>
					{/each}
				{/if}
			</div>
			</div>
		</div>

		<!-- ================= RIGHT: document ================= -->
		<div class="previewcol">
			<div class="panehead">
				<span>Preview</span>
				<span class="pl-sub">Live A4 · print exact</span>
			</div>
			<div class="previewscroll">
				{#if previewMode === 'questions'}
					<QuestionSheetPreview title={draft.title} ordered={order} numbering={num} sections={draft.sections} mode={draft.mode} />
				{:else}
					<AnswerSheetPreview
						title={draft.title} numbering={num} blocks={draft.blocks}
						overrides={draft.keyOverride} parsed={$parsedKeys} ordered={order}
						onOverride={(bid, i, t) => builder.setOverride(bid, i, t)}
					/>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.page {
		height: 100dvh;
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
	.back {
		font-weight: 600;
		font-size: 0.82rem;
		white-space: nowrap;
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
		grid-template-columns: minmax(320px, 36%) minmax(0, 1fr);
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
	}
	.panehead .pl-sub {
		font-weight: 400;
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
	.blocks {
		display: flex;
		flex-direction: column;
		gap: 8px;
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
		.topbar, .mobtabs, .undobar, .corrupt, .confirmstrip, .editor {
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
		}
	}
	@media (max-width: 900px) {
		.page {
			height: auto;
			min-height: 100dvh;
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
