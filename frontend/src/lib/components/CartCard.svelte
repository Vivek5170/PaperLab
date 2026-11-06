<script>
	/**
	 * Cart row in three sections: (A) preview link, (B) metadata,
	 * (C) actions. Paragraph groups are single items, so every
	 * reorder/remove op moves the whole block atomically.
	 */
	import { qtypeLabel } from '$lib/qtypes.js';
	import { parseParagraphRange } from '$lib/paragraph.js';

	let { item, onRemove } = $props();

	const para = $derived(parseParagraphRange(item.number, item.qtype));
	const qLabel = $derived(qtypeLabel(item.qtype).toUpperCase());
</script>

<div class="card pl-card">
	<a
		class="preview"
		href={`/cart/${item.paperId}/${encodeURIComponent(item.number)}`}
		aria-label={`Paper ${item.paperId}, question ${item.number}`}
	>
		<span class="ptext">{item.preview || 'No text preview available.'}</span>
		{#if item.thumb}
			<img class="thumb" src={item.thumb} alt="" loading="lazy" />
		{/if}
	</a>

	<div class="metablock">
		<span class="source">
			Paper {item.paperId} · Q{item.number}{item.exam ? ` · ${item.exam}` : ''}{item.year
				? ` · ${item.year}`
				: ''}
		</span>
		<span class="badges">
			{#if para.isParagraph}
				<span
					class="chip para"
					title={para.valid
						? `Passage group with ${para.count} sub-questions`
						: para.warning}
				>Passage · {para.valid ? para.count : '?'}</span>
			{/if}
			<span class="chip type" title={`Raw type ${item.qtype}`}>{qLabel}</span>
			{#if item.difficulty}
				<span class={`chip diff-${String(item.difficulty).toLowerCase()}`}>{item.difficulty}</span>
			{:else}
				<span class="nograde">Not graded</span>
			{/if}
		</span>
		{#if para.warning}
			<span class="warn" role="note">{para.warning}</span>
		{/if}
	</div>

	<div class="actions">
		<button type="button" class="rm" onclick={() => onRemove?.()}>Remove</button>
	</div>
</div>

<style>
	.card {
		display: flex;
		flex-direction: column;
		padding: 14px;
		gap: 0;
	}
	.card:hover {
		box-shadow: var(--pl-shadow-sm);
		border-color: var(--pl-seal);
	}
	.card:focus-within {
		border-color: var(--pl-seal);
	}
	/* A — preview */
	.preview {
		display: flex;
		gap: 10px;
		align-items: flex-start;
		min-height: 88px;
		text-decoration: none;
		color: inherit;
	}
	.ptext {
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
	/* B — metadata: secondary to content */
	.metablock {
		display: flex;
		flex-direction: column;
		gap: 8px;
		border-top: 1px solid var(--pl-line);
		margin-top: 10px;
		padding-top: 10px;
	}
	.source {
		font-size: 0.75rem;
		color: var(--pl-ink-soft);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.badges {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
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
	.nograde {
		font-size: 0.75rem;
		color: var(--pl-ink-soft);
	}
	.warn {
		font-size: 0.76rem;
		color: var(--pl-ochre);
		background: var(--pl-ochre-soft);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		padding: 6px 10px;
	}
	/* C — actions */
	.actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		border-top: 1px dashed var(--pl-line);
		margin-top: 10px;
		padding-top: 10px;
	}
	.rm {
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
