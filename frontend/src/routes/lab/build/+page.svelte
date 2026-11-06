<script>
	import { cartStore } from '$lib/carts.js';
	import {
		builderStore, builder, docOrder, numbering, blockTotal, builderCorrupt
	} from '$lib/builder.js';
	import { SECTION_TYPES, sectionAccepts } from '$lib/builderModel.js';
	import { normalizeAnswerType } from '$lib/qtypes.js';
	import BuilderBlock from '$lib/components/BuilderBlock.svelte';
	import KeyTable from '$lib/components/KeyTable.svelte';
	import SolutionsList from '$lib/components/SolutionsList.svelte';
	import QuestionSheetPreview from '$lib/components/QuestionSheetPreview.svelte';
	import AnswerSheetPreview from '$lib/components/AnswerSheetPreview.svelte';

	const draft = $derived($builderStore);
	const order = $derived($docOrder);
	const num = $derived($numbering);
	const nBlocks = $derived($blockTotal);

	let cartId = $state('');
	let importNote = $state('');
	let dupesNote = $state('');
	let secTitle = $state('');
	let secAtype = $state('scq');
	let renameSid = $state(null);
	let renameVal = $state('');
	let confirmNew = $state(false);
	let freshSid = $state(null);
	let previewMode = $state('questions'); // questions | answers
	let mobileTab = $state('edit'); // edit | preview (narrow screens only)
	let undoSnap = $state(null);
	let undoLabel = $state('');
	let undoTimer = null;

	$effect(() => {
		if (!cartId && $cartStore.carts.length > 0) cartId = $cartStore.activeId ?? $cartStore.carts[0].id;
	});

	const activeCart = $derived($cartStore.carts.find((c) => c.id === cartId) ?? null);
	const empty = $derived(nBlocks === 0);

	function doImport(allowDupes) {
		if (!activeCart) return;
		const r = builder.importFromCart(activeCart.items, { allowDupes });
		dupesNote = '';
		importNote =
			allowDupes || r.skipped.length === 0
				? `Imported ${r.added.length} question${r.added.length === 1 ? '' : 's'} from ${activeCart.name}.`
				: `Added ${r.added.length}; ${r.skipped.length} already in the draft (skipped).`;
		if (!allowDupes && r.skipped.length > 0)
			dupesNote = `${r.skipped.length} duplicate${r.skipped.length === 1 ? '' : 's'} skipped.`;
	}

	function addSection() {
		if (!secTitle.trim()) return;
		const id = builder.addSection({ title: secTitle.trim(), atype: secAtype });
		secTitle = '';
		if (id) {
			freshSid = id;
			setTimeout(() => (freshSid = null), 2600);
			setTimeout(() => document.getElementById(`sec-${id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 60);
		}
	}

	function saveRename(sid) {
		if (renameVal.trim()) builder.renameSection(sid, renameVal);
		renameSid = null;
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
		if (!ok) importNote = 'Could not undo — the section is gone. Re-import the question from its cart.';
	}
</script>

<svelte:head><title>Paper Builder - PaperLab</title></svelte:head>

<a class="back" href="/cart">← Back to Cart</a>
<h1>Paper builder</h1>
<p class="pl-sub">
	Experimental. Drafts live only in this browser. Numbering is continuous and
	generated — original extraction ids are shown as source only.
</p>

{#if $builderCorrupt}
	<div class="pl-error" role="alert">
		<strong>Saved builder draft was corrupt.</strong>
		<p class="pl-mono">Started fresh; the broken copy was backed up in this browser.</p>
		<button type="button" class="pl-btn" onclick={() => builderCorrupt.set(false)}>Dismiss</button>
	</div>
{/if}

{#if undoSnap}
	<div class="undobar" role="status">
		<span>Removed {undoLabel}.</span>
		<button type="button" class="pl-btn" onclick={undoRemove}>Undo</button>
	</div>
{/if}

<nav class="mobtabs" role="tablist" aria-label="Builder view">
	<button type="button" role="tab" aria-selected={mobileTab === 'edit'} class:active={mobileTab === 'edit'} onclick={() => (mobileTab = 'edit')}>Editor</button>
	<button type="button" role="tab" aria-selected={mobileTab === 'preview'} class:active={mobileTab === 'preview'} onclick={() => (mobileTab = 'preview')}>Preview</button>
</nav>

<div class="workspace" data-view={mobileTab}>
	<!-- ================= LEFT: editor ================= -->
	<div class="editor" role="tabpanel" aria-label="Editor">
		<div class="panel pl-card">
			<label class="title">
				<span class="pl-sub">Title</span>
				<input
					type="text" value={draft.title} placeholder="Untitled paper"
					maxlength="120" aria-label="Draft title"
					oninput={(e) => builder.setTitle(e.currentTarget.value)}
				/>
			</label>
			<div class="moderow" role="radiogroup" aria-label="Draft mode">
				<label class:off={!empty && draft.mode !== 'paper'}>
					<input type="radio" name="mode" checked={draft.mode === 'paper'} disabled={!empty} onchange={() => builder.newDraft('paper')} />
					Question paper <span class="pl-sub">(typed sections)</span>
				</label>
				<label class:off={!empty && draft.mode !== 'assignment'}>
					<input type="radio" name="mode" checked={draft.mode === 'assignment'} disabled={!empty} onchange={() => builder.newDraft('assignment')} />
					Assignment <span class="pl-sub">(flat, mixed)</span>
				</label>
				{#if !empty}
					<span class="pl-sub">Mode locks once questions are added — start a new draft to switch.</span>
				{/if}
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
					Import{activeCart ? ` ${activeCart.items.length}` : ''} questions
				</button>
				{#if draft.mode === 'paper' && !empty}
					<button type="button" class="pl-btn" onclick={() => builder.autoGroup()}>Auto-group by type</button>
				{/if}
			</div>
			{#if draft.mode === 'paper'}
				<p class="pl-sub">Singles group by answer type; every passage — uniform or mixed — goes to a Passage section, never split.</p>
			{/if}
			{#if importNote}<p class="pl-sub" role="status">{importNote}</p>{/if}
			{#if dupesNote}
				<p class="pl-sub" role="status">
					{dupesNote}
					<button type="button" class="pl-btn" onclick={() => doImport(true)}>Import including duplicates</button>
				</p>
			{/if}
		</div>

		<div class="panel pl-card">
			<div class="sechead">
				<h2>{draft.mode === 'paper' ? 'Sections' : 'Questions'} · {nBlocks} block{nBlocks === 1 ? '' : 's'} → {num.total} number{num.total === 1 ? '' : 's'}</h2>
				{#if draft.mode === 'paper'}
					<div class="addsec">
						<input type="text" bind:value={secTitle} placeholder="New section title" maxlength="80" aria-label="New section title" />
						<select bind:value={secAtype} aria-label="New section type">
							{#each SECTION_TYPES as t (t)}
								<option value={t}>{t.toUpperCase()}</option>
							{/each}
						</select>
						<button type="button" class="pl-btn" disabled={!secTitle.trim()} onclick={addSection}>Add section</button>
					</div>
				{/if}
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
								sections={[]}
								showSectionMove={false}
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
					<section class="section" class:fresh={freshSid === s.id} id={`sec-${s.id}`} aria-label={s.title}>
						<div class="stitle">
							{#if renameSid === s.id}
								<input
									type="text" value={renameVal} maxlength="80" aria-label="Section title"
									oninput={(e) => (renameVal = e.currentTarget.value)}
									onkeydown={(e) => {
										if (e.key === 'Enter') saveRename(s.id);
										else if (e.key === 'Escape') renameSid = null;
									}}
								/>
								<button type="button" class="pl-btn" onclick={() => saveRename(s.id)}>Save</button>
								<button type="button" class="pl-btn" onclick={() => (renameSid = null)}>Cancel</button>
							{:else}
								<strong>{s.title}</strong>
								{#if s.blockIds.length === 0}
									<select value={s.atype} onchange={(e) => builder.setSectionAtype(s.id, e.currentTarget.value)} aria-label={`Type for ${s.title}`}>
										{#each SECTION_TYPES as t (t)}
											<option value={t}>{t.toUpperCase()}</option>
										{/each}
									</select>
								{:else if s.atype === 'passage'}
									<span class="atype passage" title="Structural group: passages stay whole, children keep their own types">PASSAGE</span>
								{:else}
									<span class="atype" title={`Accepts ${s.atype} (par-${s.atype} merges here)`}>{s.atype.toUpperCase()}</span>
								{/if}
								<span class="pl-sub">{s.blockIds.length} block{s.blockIds.length === 1 ? '' : 's'}</span>
								<span class="sops">
									<button type="button" class="mini" onclick={() => { renameSid = s.id; renameVal = s.title; }}>Rename</button>
									<button type="button" class="mini icon" disabled={si === 0} onclick={() => builder.moveSection(si, si - 1)} title="Move section up" aria-label={`Move ${s.title} up`}>
										<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6-6"/></svg>
									</button>
									<button type="button" class="mini icon" disabled={si === draft.sections.length - 1} onclick={() => builder.moveSection(si, si + 1)} title="Move section down" aria-label={`Move ${s.title} down`}>
										<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14m-6-6 6 6 6-6"/></svg>
									</button>
									{#if s.blockIds.length === 0}
										<button type="button" class="mini danger" onclick={() => builder.deleteSection(s.id)}>Delete</button>
									{:else}
										<button type="button" class="mini" disabled title="Move all blocks out first">Delete</button>
									{/if}
								</span>
							{/if}
						</div>
						{#if s.atype === 'passage' && s.blockIds.length > 0}
							<p class="pl-sub passage-note">Passages stay whole; child questions keep their own types and numbers.</p>
						{/if}
						<div class="blocks">
							{#each s.blockIds as bid (bid)}
								{@const b = draft.blocks[bid]}
								{#if b}
									{@const expected = s.atype === 'passage' ? null : normalizeAnswerType(b.qtype)}
									<BuilderBlock
										block={b}
										numbers={num.byBlock[bid] ?? []}
										sections={draft.sections}
										currentSectionId={s.id}
										showSectionMove={draft.sections.length > 1}
										onUp={() => builder.moveBlock(bid, -1)}
										onDown={() => builder.moveBlock(bid, 1)}
										onMoveTo={(target) => builder.moveBlockToSection(bid, target)}
										onRemove={() => removeWithUndo(bid, `${(num.byBlock[bid] ?? []).map((n) => `Q${n}`).join('–')} (Paper ${b.paperId} · ${b.number})`)}
									/>
									{#if expected && expected !== s.atype}
										<p class="pl-error mini-note" role="note">Type drift: {b.qtype} no longer matches this {s.atype.toUpperCase()} section. Move it out.</p>
									{/if}
								{/if}
							{:else}
								<p class="pl-sub">Empty section — excluded from numbering until it holds a block.</p>
							{/each}
						</div>
					</section>
				{/each}
			{/if}
		</div>

		<div class="panel pl-card">
			<KeyTable numbering={num} blocks={draft.blocks} overrides={draft.keyOverride} onOverride={(bid, i, t) => builder.setOverride(bid, i, t)} />
		</div>

		<div class="panel pl-card">
			<h2 class="solhead">Solution status</h2>
			<p class="pl-sub">Each block loads its filed solution. Missing solutions keep their numbering and key rows.</p>
			<SolutionsList ordered={order} numbering={num} />
		</div>

		<div class="panel danger-zone">
			{#if confirmNew}
				<button type="button" class="pl-btn danger" onclick={() => { builder.newDraft(draft.mode); confirmNew = false; }}>Confirm: discard this draft</button>
				<button type="button" class="pl-btn" onclick={() => (confirmNew = false)}>Keep</button>
			{:else}
				<button type="button" class="pl-btn" onclick={() => (confirmNew = true)}>Start new draft</button>
			{/if}
		</div>
	</div>

	<!-- ================= RIGHT: live preview ================= -->
	<div class="previewcol" role="tabpanel" aria-label="Preview">
		<div class="previewbar">
			<div class="seg" role="group" aria-label="Preview mode">
				<button type="button" class:active={previewMode === 'questions'} aria-pressed={previewMode === 'questions'} onclick={() => (previewMode = 'questions')}>Question Sheet</button>
				<button type="button" class:active={previewMode === 'answers'} aria-pressed={previewMode === 'answers'} onclick={() => (previewMode = 'answers')}>Answer Sheet</button>
			</div>
			<span class="pl-sub">Live · {num.total} numbers</span>
		</div>
		<div class="previewscroll">
			{#if previewMode === 'questions'}
				<QuestionSheetPreview title={draft.title} ordered={order} numbering={num} sections={draft.sections} mode={draft.mode} />
			{:else}
				<AnswerSheetPreview title={draft.title} numbering={num} blocks={draft.blocks} overrides={draft.keyOverride} />
			{/if}
		</div>
	</div>
</div>

<style>
	.back {
		display: inline-block;
		margin-bottom: 12px;
		font-weight: 600;
		font-size: 0.85rem;
	}
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.undobar {
		display: flex;
		align-items: center;
		gap: 12px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		background: var(--pl-surface);
		padding: 8px 12px;
		margin: 12px 0 0;
		font-size: 0.85rem;
	}
	/* mobile tabs (desktop: both panels visible) */
	.mobtabs {
		display: none;
		gap: 4px;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		padding: 4px;
		margin: 14px 0;
		width: max-content;
	}
	.mobtabs button {
		border: none;
		background: none;
		border-radius: var(--pl-radius-pill);
		padding: 8px 18px;
		min-height: 0;
		font-size: 0.82rem;
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
		display: grid;
		grid-template-columns: minmax(420px, 560px) minmax(0, 1fr);
		gap: 20px;
		align-items: start;
		margin-top: 4px;
		max-width: 1460px;
	}
	.editor {
		display: flex;
		flex-direction: column;
		gap: 0;
		min-width: 0;
	}
	.panel {
		margin-top: 16px;
		padding: 16px;
	}
	.panel h2 {
		margin: 0 0 10px;
		font-size: 1.15rem;
	}
	.solhead {
		margin: 0 0 2px;
		font-size: 1.15rem;
	}
	.title {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-bottom: 12px;
	}
	.title input {
		font-size: 1rem;
	}
	.moderow {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 20px;
		align-items: center;
	}
	.moderow label {
		display: flex;
		gap: 8px;
		align-items: center;
		font-weight: 600;
		cursor: pointer;
	}
	.moderow label.off {
		opacity: 0.55;
		cursor: default;
	}
	.moderow input[type='radio'] {
		min-height: 0;
		width: 18px;
		height: 18px;
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
	}
	.sechead {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 12px;
	}
	.sechead h2 {
		margin: 0;
	}
	.addsec {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}
	.addsec input {
		min-width: 150px;
		flex: 1;
	}
	.warns {
		margin: 0 0 12px;
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
		padding: 12px;
		margin-bottom: 12px;
		background: var(--pl-paper);
		scroll-margin-top: 12px;
	}
	.section.fresh {
		border-color: var(--pl-seal);
		box-shadow: 0 0 0 2px var(--pl-seal-soft);
	}
	.stitle {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		align-items: center;
		margin-bottom: 10px;
	}
	.stitle strong {
		font-size: 1rem;
	}
	.atype {
		font-size: 0.72rem;
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
	.passage-note {
		margin: -4px 0 10px;
		font-size: 0.78rem;
	}
	.sops {
		margin-left: auto;
		display: flex;
		gap: 4px;
	}
	.mini {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		background: none;
		min-height: 32px;
		padding: 4px 12px;
		font-size: 0.78rem;
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
	.mini.danger {
		color: var(--pl-seal);
	}
	.mini.icon {
		padding: 4px 10px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}
	.mini.icon svg {
		width: 14px;
		height: 14px;
	}
	.mini-note {
		font-size: 0.78rem;
		margin: 6px 0 0;
	}
	.blocks {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.danger-zone {
		margin-top: 16px;
		display: flex;
		gap: 8px;
	}
	.danger {
		color: var(--pl-seal);
		border-color: var(--pl-seal);
	}
	/* RIGHT: preview */
	.previewcol {
		position: sticky;
		top: 12px;
		max-height: calc(100dvh - 24px);
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.previewbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		margin-top: 16px;
		margin-bottom: 10px;
	}
	.seg {
		display: inline-flex;
		gap: 4px;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		padding: 4px;
	}
	.seg button {
		border: none;
		background: none;
		border-radius: var(--pl-radius-pill);
		padding: 8px 18px;
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
	.previewscroll {
		overflow-y: auto;
		min-height: 0;
		padding-bottom: 24px;
	}
	@media (max-width: 1100px) {
		.workspace {
			grid-template-columns: minmax(360px, 440px) minmax(0, 1fr);
		}
	}
	@media (max-width: 900px) {
		.mobtabs {
			display: inline-flex;
		}
		.workspace {
			grid-template-columns: 1fr;
		}
		.previewcol {
			position: static;
			max-height: none;
		}
		.workspace[data-view='edit'] .previewcol,
		.workspace[data-view='preview'] .editor {
			display: none;
		}
		.sops {
			margin-left: 0;
		}
	}
</style>
