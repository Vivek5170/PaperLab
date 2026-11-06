<script>
	/**
	 * Cart row: visual clone of the search card (preview + thumb + chips)
	 * plus source line, paragraph badge/warning, and cart actions.
	 * Never renders stored HTML — preview is plain text only.
	 */
	import { qtypeLabel } from '$lib/qtypes.js';
	import { normalizeAnswerType } from '$lib/qtypes.js';
	import { parseParagraphRange } from '$lib/paragraph.js';

	let { item, index = 0, total = 0, onMove, onRemove } = $props();

	const para = $derived(parseParagraphRange(item.number, item.qtype));
	const ansType = $derived(normalizeAnswerType(item.qtype));
</script>

<div class="card pl-card">
	<a
		class="main"
		href={`/search/${item.paperId}/${encodeURIComponent(item.number)}`}
		aria-label={`Paper ${item.paperId}, question ${item.number}`}
	>
		<span class="top">
			<span class="preview">{item.preview || 'No text preview available.'}</span>
			{#if item.thumb}
				<img class="thumb" src={item.thumb} alt="" loading="lazy" />
			{/if}
		</span>
		<span class="meta">
			<span class="paperline">
				Paper {item.paperId} · Q{item.number}{item.exam ? ` · ${item.exam}` : ''}{item.year
					? ` · ${item.year}`
					: ''}
			</span>
			<span class="chips">
				{#if item.difficulty}
					<span class={`chip diff-${String(item.difficulty).toLowerCase()}`}>{item.difficulty}</span>
				{/if}
				<span class="chip type" title={item.qtype}>{qtypeLabel(item.qtype)}</span>
				{#if para.isParagraph}
					<span class="chip para" title={para.valid
						? `Passage group: ${para.count} sub-questions`
						: para.warning}>Passage · {para.valid ? para.count : '?'}</span>
				{/if}
			</span>
		</span>
		{#if para.warning}
			<span class="warn" role="note">{para.warning}</span>
		{/if}
		{#if ansType !== (item.qtype ?? '').toLowerCase()}
			<span class="pl-sub norm">Groups under {ansType.toUpperCase()} in the builder</span>
		{/if}
	</a>
	<div class="actions">
		<div class="mv" role="group" aria-label={`Reorder question ${item.number}`}>
			<button type="button" disabled={index === 0} onclick={() => onMove?.(index, 0)} title="Move to top">⇤</button>
			<button type="button" disabled={index === 0} onclick={() => onMove?.(index, index - 1)} title="Move up">↑</button>
			<button type="button" disabled={index === total - 1} onclick={() => onMove?.(index, index + 1)} title="Move down">↓</button>
			<button type="button" disabled={index === total - 1} onclick={() => onMove?.(index, total - 1)} title="Move to bottom">⇥</button>
		</div>
		<button type="button" class="rm" onclick={() => onRemove?.()}>Remove</button>
	</div>
</div>

<style>
	.card {
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 14px;
	}
	.main {
		display: flex;
		flex-direction: column;
		gap: 10px;
		text-decoration: none;
		color: inherit;
	}
	.top {
		display: flex;
		gap: 10px;
		align-items: flex-start;
		min-height: 72px;
	}
	.preview {
		flex: 1;
		min-width: 0;
		font-size: 0.86rem;
		line-height: 1.5;
		display: -webkit-box;
		-webkit-line-clamp: 4;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.thumb {
		width: 76px;
		height: 76px;
		object-fit: cover;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-raised);
		flex-shrink: 0;
	}
	.meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		border-top: 1px solid var(--pl-line);
		padding-top: 10px;
	}
	.paperline {
		font-size: 0.75rem;
		color: var(--pl-ink-soft);
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.chips {
		display: flex;
		gap: 6px;
		flex-shrink: 0;
		flex-wrap: wrap;
		justify-content: flex-end;
	}
	.chip {
		border-radius: 6px;
		padding: 2px 8px;
		font-size: 0.72rem;
		font-weight: 600;
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
	.diff-easy {
		background: var(--pl-pine-soft);
		color: var(--pl-pine);
	}
	.diff-medium {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.diff-hard {
		background: var(--pl-seal-soft);
		color: var(--pl-seal);
	}
	.warn {
		font-size: 0.76rem;
		color: var(--pl-ochre);
		background: var(--pl-ochre-soft);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		padding: 6px 10px;
	}
	.norm {
		font-size: 0.75rem;
	}
	.actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		border-top: 1px dashed var(--pl-line);
		padding-top: 10px;
	}
	.mv {
		display: flex;
		gap: 4px;
	}
	.mv button {
		border: 1px solid var(--pl-line);
		background: none;
		border-radius: 6px;
		min-width: 32px;
		min-height: 32px;
		cursor: pointer;
	}
	.mv button:disabled {
		opacity: 0.35;
		cursor: default;
	}
	.rm {
		border: 1px solid var(--pl-line);
		background: none;
		border-radius: 6px;
		padding: 6px 12px;
		min-height: 32px;
		font-size: 0.78rem;
		font-weight: 600;
		cursor: pointer;
		color: var(--pl-seal);
	}
</style>
