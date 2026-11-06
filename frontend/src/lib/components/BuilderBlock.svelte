<script>
	/**
	 * One builder question row (compact list style). Numbering arrives as
	 * a prop from the page's single assignNumbers() result — this component
	 * never numbers. Sections are fully derived (auto A/B/C), so blocks
	 * only move within their section or get removed (undoable).
	 */
	import { qtypeLabel } from '$lib/qtypes.js';
	import { parseParagraphRange } from '$lib/paragraph.js';
	import { numberLabel } from '$lib/numbering.js';
	import { onMount } from 'svelte';

	let { block, numbers = [], showType = true, onUp, onDown, onRemove, onDragStart, onDropRow, canDrop } = $props();

	const para = $derived(parseParagraphRange(block.number, block.qtype));
	const label = $derived(numberLabel(numbers));

	// Grip-armed native drag: the row is draggable only while the grip is
	// held, so text stays selectable and clicks stay clicks everywhere else.
	let armed = $state(false);
	let rowEl = $state(null);

	onMount(() => {
		// Pressing the grip without dragging must not leave the row armed.
		const up = () => {
			armed = false;
		};
		window.addEventListener('mouseup', up);
		return () => window.removeEventListener('mouseup', up);
	});

	function clearHints() {
		rowEl?.classList?.remove('drop-above', 'drop-below', 'dragging');
	}
	function disarm() {
		armed = false;
		clearHints();
	}
	function handleDragStart(e) {
		if (!armed || !onDropRow) {
			e.preventDefault();
			return;
		}
		try {
			e.dataTransfer.setData('text/plain', block.id);
			e.dataTransfer.effectAllowed = 'move';
		} catch { /* ignore */ }
		rowEl?.classList?.add('dragging');
		onDragStart?.(block.id);
	}
	function handleDragOver(e) {
		if (!onDropRow) return;
		e.preventDefault();
		e.stopPropagation();
		if (canDrop?.(block.id) === false) {
			try {
				e.dataTransfer.dropEffect = 'none';
			} catch { /* ignore */ }
			clearHints();
			return;
		}
		try {
			e.dataTransfer.dropEffect = 'move';
		} catch { /* ignore */ }
		if (!rowEl || rowEl.classList.contains('dragging')) return;
		const r = rowEl.getBoundingClientRect();
		const above = (e.clientY - r.top) < r.height / 2;
		rowEl.classList.toggle('drop-above', above);
		rowEl.classList.toggle('drop-below', !above);
	}
	function handleDrop(e) {
		if (!onDropRow) return;
		e.preventDefault();
		e.stopPropagation();
		if (!rowEl) return;
		const r = rowEl.getBoundingClientRect();
		const pos = (e.clientY - r.top) < r.height / 2 ? 'before' : 'after';
		clearHints();
		disarm();
		onDropRow(block.id, pos);
	}
</script>

<div
	class="qrow"
	data-block={block.id}
	bind:this={rowEl}
	draggable={armed}
	ondragstart={handleDragStart}
	ondragend={disarm}
	ondragover={handleDragOver}
	ondragleave={clearHints}
	ondrop={handleDrop}
>
	<span
		class="grip" aria-hidden="true" title="Drag to reorder"
		onmousedown={() => (armed = true)}
		ontouchstart={() => (armed = true)}
	>
		<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>
	</span>
	<span class="qnum" title="Generated number — independent of the original extraction">{label}</span>
	<span class="src">Paper {block.paperId} · Q{block.number}</span>
	{#if para.isParagraph}
		<span
			class="chip para"
			title={para.valid ? `Passage group: ${para.count} sub-questions` : para.warning}
		>P·{para.valid ? para.count : '?'}</span>
	{/if}
	{#if showType}
		<span class="chip type" title={`Raw type ${block.qtype}`}>{qtypeLabel(block.qtype).toUpperCase()}</span>
	{/if}
	<span class="rowops">
		<span class="mv" role="group" aria-label={`Reorder block ${label}`}>
			<button type="button" onclick={onUp} title="Move up" aria-label={`Move ${label} up`}>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg>
			</button>
			<button type="button" onclick={onDown} title="Move down" aria-label={`Move ${label} down`}>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14m-6-6 6 6 6 6"/></svg>
			</button>
		</span>
		<button type="button" class="rmicon" onclick={onRemove} title={`Remove ${label} (undo available)`} aria-label={`Remove ${label}`}>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>
		</button>
	</span>
</div>
{#if para.warning}
	<p class="warn" role="note">{para.warning}</p>
{/if}

<style>
	.qrow {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 6px;
		border-bottom: 1px solid var(--pl-line);
		border-radius: 6px;
		min-width: 0;
	}
	.qrow:hover {
		background: var(--pl-raised);
	}
	.qrow.dragging {
		opacity: 0.45;
	}
	.qrow.drop-above {
		box-shadow: 0 -2px 0 var(--pl-seal);
	}
	.qrow.drop-below {
		box-shadow: 0 2px 0 var(--pl-seal);
	}
	.grip {
		display: inline-flex;
		color: var(--pl-ink-soft);
		opacity: 0.7;
		cursor: grab;
		flex-shrink: 0;
	}
	.grip svg {
		width: 14px;
		height: 14px;
	}
	.qnum {
		font-weight: 700;
		font-size: 0.82rem;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		padding: 1px 8px;
		white-space: nowrap;
		flex-shrink: 0;
	}
	.src {
		font-size: 0.74rem;
		color: var(--pl-ink-soft);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}
	.chip {
		border-radius: 6px;
		padding: 1px 7px;
		font-size: 0.68rem;
		font-weight: 600;
		line-height: 1.55;
		flex-shrink: 0;
	}
	.chip.type {
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		font-family: var(--pl-font-mono);
		font-weight: 500;
	}
	.chip.para {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.rowops {
		margin-left: auto;
		display: inline-flex;
		align-items: center;
		gap: 2px;
		flex-shrink: 0;
	}
	.mv {
		display: inline-flex;
		gap: 2px;
		align-items: center;
	}
	.mv button,
	.rmicon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		min-height: 0;
		border: 1px solid transparent;
		border-radius: 6px;
		background: none;
		color: var(--pl-ink-soft);
		cursor: pointer;
		padding: 0;
	}
	.mv button:hover,
	.rmicon:hover {
		border-color: var(--pl-line);
		background: var(--pl-surface);
		color: var(--pl-ink);
	}
	.rmicon:hover {
		color: var(--pl-seal);
		border-color: var(--pl-seal);
		background: var(--pl-seal-soft);
	}
	.mv svg,
	.rmicon svg {
		width: 13px;
		height: 13px;
	}
	.warn {
		font-size: 0.74rem;
		color: var(--pl-ochre);
		margin: 2px 0 6px 22px;
	}
</style>
