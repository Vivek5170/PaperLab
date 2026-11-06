<script>
	/**
	 * One builder block row. Numbering arrives as a prop from the page's
	 * single assignNumbers() result — this component never numbers.
	 * Sections are fully derived (auto A/B/C), so blocks only move
	 * within their section or get removed (undoable).
	 */
	import { qtypeLabel } from '$lib/qtypes.js';
	import { parseParagraphRange } from '$lib/paragraph.js';
	import { numberLabel } from '$lib/numbering.js';

	let { block, numbers = [], onUp, onDown, onRemove } = $props();

	const para = $derived(parseParagraphRange(block.number, block.qtype));
	const label = $derived(numberLabel(numbers));
</script>

<div class="block pl-card">
	<div class="line">
		<span class="qnum" title="Generated number — independent of the original extraction">{label}</span>
		<span class="src">Paper {block.paperId} · Q{block.number}</span>
		<span class="badges">
			{#if para.isParagraph}
				<span
					class="chip para"
					title={para.valid ? `Passage group: ${para.count} sub-questions` : para.warning}
				>Passage · {para.valid ? para.count : '?'}</span>
			{/if}
			<span class="chip type" title={`Raw type ${block.qtype}`}>{qtypeLabel(block.qtype).toUpperCase()}</span>
		</span>
	</div>
	{#if para.warning}
		<span class="warn" role="note">{para.warning}</span>
	{/if}
	<div class="ops">
		<div class="mv" role="group" aria-label={`Reorder block ${label}`}>
			<button type="button" onclick={onUp} title="Move up" aria-label={`Move ${label} up`}>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6-6"/></svg>
			</button>
			<button type="button" onclick={onDown} title="Move down" aria-label={`Move ${label} down`}>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14m-6-6 6 6 6-6"/></svg>
			</button>
		</div>
		<button type="button" class="rm" onclick={onRemove}>Remove</button>
	</div>
</div>

<style>
	.block {
		padding: 10px 12px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.line {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}
	.qnum {
		font-weight: 700;
		font-size: 0.95rem;
		background: var(--pl-raised);
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		padding: 2px 10px;
		white-space: nowrap;
	}
	.src {
		font-size: 0.78rem;
		color: var(--pl-ink-soft);
	}
	.badges {
		display: flex;
		gap: 6px;
		margin-left: auto;
		align-items: center;
	}
	.chip {
		border-radius: 6px;
		padding: 2px 8px;
		font-size: 0.72rem;
		font-weight: 600;
		line-height: 1.55;
	}
	.chip.type {
		background: var(--pl-raised);
		font-family: var(--pl-font-mono);
		font-weight: 500;
	}
	.chip.para {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.warn {
		font-size: 0.76rem;
		color: var(--pl-ochre);
	}
	.ops {
		display: flex;
		align-items: center;
		gap: 8px;
		border-top: 1px dashed var(--pl-line);
		padding-top: 8px;
	}
	.mv {
		display: flex;
		gap: 4px;
		align-items: center;
	}
	.mv button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		min-height: 0;
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		background: none;
		color: var(--pl-ink-soft);
		cursor: pointer;
		padding: 0;
	}
	.mv button:hover {
		border-color: var(--pl-seal);
		color: var(--pl-seal);
	}
	.mv svg {
		width: 15px;
		height: 15px;
	}
	.rm {
		margin-left: auto;
		border: 1px solid var(--pl-line);
		border-radius: 6px;
		background: none;
		padding: 6px 12px;
		min-height: 32px;
		font-size: 0.78rem;
		font-weight: 600;
		cursor: pointer;
		color: var(--pl-seal);
	}
	.rm:hover {
		border-color: var(--pl-seal);
		background: var(--pl-seal-soft);
	}
</style>
