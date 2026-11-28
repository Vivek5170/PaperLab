<script>
	/**
	 * One EJEE item: original source pages (question, then worked solution),
	 * its metadata and the 15-question part it belongs to. Images are
	 * read-only previews of the EJEE uploads (body crop).
	 */
	import { api, img, fullImg } from '$lib/api.js';
	import { answerLabel } from '$lib/labels.js';
	import PartButton from '$lib/components/PartButton.svelte';

	let { source, itemKey, compact = false, onpick = null } = $props();

	let data = $state(null);
	let error = $state('');
	let tab = $state('question');

	async function load() {
		error = '';
		data = null;
		tab = 'question';
		try {
			data = await api.item(source, itemKey);
		} catch (e) {
			error = e.message;
		}
	}

	$effect(() => {
		source;
		itemKey;
		load();
	});

	const pages = $derived(
		!data ? [] : tab === 'solution' ? data.solutionIds : data.questionIds
	);
</script>

{#if error}
	<div class="pl-error" role="alert">
		<p>{error}</p>
		<button type="button" class="pl-btn" onclick={load}>Retry</button>
	</div>
{:else if !data}
	<p class="pl-sub">Loading…</p>
{:else}
	<article class="reader" class:compact>
		<header>
			<p class="eyebrow">{data.category}{data.collection ? ` · ${data.collection}` : ''}</p>
			<h2>{data.label}</h2>
			<p class="pl-sub src">{data.source}</p>
			<div class="chips">
				{#if data.difficulty}<span class={`chip diff-${data.difficulty.toLowerCase()}`}>{data.difficulty}</span>{/if}
				{#if data.qtype}<span class="chip type">{data.qtype}</span>{/if}
				{#if data.exam}<span class="chip">{data.exam}{data.year ? ` ${data.year}` : ''}</span>{/if}
				<span class="chip">{answerLabel(data.answer)}</span>
			</div>
		</header>

		<section class="partbox" aria-label="Conversion part">
			<div>
				<strong>Part {data.part}</strong>
				<span class="pl-sub">
					· question {data.localNo} of {data.partItems?.length ?? 15}{data.sourceInfo?.parts ? ` · ${data.sourceInfo.parts} part${data.sourceInfo.parts === 1 ? '' : 's'} in this source` : ''}
				</span>
			</div>
			<PartButton item={data} size="lg" onchange={(s) => (data = { ...data, status: s })} />
		</section>

		<div class="tabs" role="tablist" aria-label="Source pages">
			<button type="button" role="tab" aria-selected={tab === 'question'} class:on={tab === 'question'}
				onclick={() => (tab = 'question')}>Question · {data.questionIds.length}</button>
			<button type="button" role="tab" aria-selected={tab === 'solution'} class:on={tab === 'solution'}
				disabled={!data.solutionIds.length} onclick={() => (tab = 'solution')}>
				Solution · {data.solutionIds.length}
			</button>
			{#if data.preview}
				<button type="button" role="tab" aria-selected={tab === 'text'} class:on={tab === 'text'}
					onclick={() => (tab = 'text')}>EJEE text</button>
			{/if}
		</div>

		{#if tab === 'text'}
			<pre class="ejeetext">{data.preview}</pre>
			<p class="pl-hint">Existing EJEE transcription (evidence only). The importer transcribes from the image.</p>
		{:else}
			<div class="pages">
				{#each pages as rid, i (rid)}
					<figure>
						<img class="srcimg" src={img(rid, compact ? 960 : 1600)} alt={`${tab} page ${i + 1} of ${data.label}`} loading="lazy" />
						<figcaption>
							<span class="pl-mono">Page {i + 1} · resource {rid}</span>
							<a href={fullImg(rid)} target="_blank" rel="noopener">Full original</a>
						</figcaption>
					</figure>
				{/each}
			</div>
		{/if}

		<dl class="meta">
			<dt>Source</dt><dd>{data.source}</dd>
			<dt>Category</dt><dd>{data.category}</dd>
			{#if data.topicPath?.length}<dt>EJEE topic</dt><dd>{data.topicPath.join(' › ')}</dd>{/if}
			<dt>Item</dt><dd class="pl-mono">{data.key}</dd>
		</dl>

		{#if data.partItems?.length}
			<section aria-label={`Questions in part ${data.part}`}>
				<h3>In Part {data.part}</h3>
				<ol class="partlist">
					{#each data.partItems as p (p.key)}
						<li class:cur={p.key === data.key}>
							{#if onpick}
								<button type="button" onclick={() => onpick({ source: data.source, key: p.key })}>
									<span class="n pl-mono">{p.localNo}</span><span class="lb">{p.label}</span>
								</button>
							{:else}
								<a href={`/item?source=${encodeURIComponent(data.source)}&key=${encodeURIComponent(p.key)}`}>
									<span class="n pl-mono">{p.localNo}</span><span class="lb">{p.label}</span>
								</a>
							{/if}
						</li>
					{/each}
				</ol>
			</section>
		{/if}
	</article>
{/if}

<style>
	.reader {
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.eyebrow {
		margin: 0 0 4px;
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--pl-ink-soft);
	}
	h2 {
		font-size: 1.5rem;
	}
	.compact h2 {
		font-size: 1.25rem;
	}
	.src {
		margin: 4px 0 8px;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.chip {
		border-radius: 6px;
		padding: 2px 8px;
		font-size: 0.75rem;
		font-weight: 600;
		background: var(--pl-raised);
	}
	.chip.type {
		font-family: var(--pl-font-mono);
		font-weight: 500;
	}
	.diff-easy {
		background: var(--pl-pine-soft);
		color: var(--pl-pine);
	}
	.diff-medium {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.diff-hard,
	.diff-olympiad {
		background: var(--pl-seal-soft);
		color: var(--pl-seal);
	}
	.partbox {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		background: var(--pl-surface);
		padding: 12px 14px;
	}
	.tabs {
		display: flex;
		gap: 4px;
		border-bottom: 1px solid var(--pl-line);
	}
	.tabs button {
		border: none;
		background: none;
		padding: 8px 14px;
		font-weight: 600;
		font-size: 0.85rem;
		color: var(--pl-ink-soft);
		border-bottom: 2px solid transparent;
		min-height: 40px;
	}
	.tabs button.on {
		color: var(--pl-ink);
		border-bottom-color: var(--pl-seal);
	}
	.tabs button:disabled {
		opacity: 0.45;
	}
	.pages {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	figure {
		margin: 0;
	}
	.srcimg {
		display: block;
		width: 100%;
		height: auto;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: #fff;
	}
	figcaption {
		display: flex;
		justify-content: space-between;
		gap: 8px;
		font-size: 0.78rem;
		color: var(--pl-ink-soft);
		margin-top: 4px;
	}
	.ejeetext {
		white-space: pre-wrap;
		font-family: var(--pl-font-ui);
		font-size: 0.9rem;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		padding: 12px;
		margin: 0;
	}
	.meta {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 6px 14px;
		margin: 0;
		font-size: 0.85rem;
	}
	.meta dt {
		color: var(--pl-ink-soft);
	}
	.meta dd {
		margin: 0;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	h3 {
		font-size: 1.05rem;
		margin-bottom: 8px;
	}
	.partlist {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.partlist a,
	.partlist button {
		display: flex;
		gap: 10px;
		align-items: baseline;
		width: 100%;
		text-align: left;
		border: none;
		background: none;
		padding: 6px 8px;
		border-radius: var(--pl-radius-sm);
		text-decoration: none;
		font-size: 0.85rem;
		min-height: 36px;
	}
	.partlist a:hover,
	.partlist button:hover {
		background: var(--pl-raised);
	}
	.partlist .cur a,
	.partlist .cur button {
		background: var(--pl-seal-soft);
		font-weight: 600;
	}
	.partlist .n {
		color: var(--pl-ink-soft);
		min-width: 2ch;
		text-align: right;
	}
	.partlist .lb {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
