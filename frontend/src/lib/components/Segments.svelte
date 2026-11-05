<script>
	import katex from 'katex';
	import 'katex/dist/katex.min.css';

	/**
	 * Renders backend segments. Text/table cells arrive as HTML with math
	 * placeholders (<span class="pl-math[data-tex]">) produced by the exact
	 * Streamlit splitting rules; this component only fills them with KaTeX.
	 */
	let { segments = [], bust = '', zoomable = false } = $props();

	/** Click-to-zoom lightbox. Opt-in (zoomable) so existing uses are unaffected. */

	let el = $state(null);
	let zoom = $state(null);

	function withBust(url) {
		return bust && url.startsWith('/api/') ? `${url}?v=${bust}` : url;
	}

	function closeZoom() {
		zoom = null;
	}

	$effect(() => {
		if (!el) return;
		// Track segments so new content re-renders math.
		void segments;
		for (const node of el.querySelectorAll('.pl-math, .pl-math-block')) {
			if (node.dataset.done) continue;
			const tex = decodeURIComponent(node.dataset.tex || '');
			let html = '';
			try {
				html = katex.renderToString(tex, {
					displayMode: node.classList.contains('pl-math-block'),
					throwOnError: false
				});
			} catch {
				html = '';
			}
			node.innerHTML = html;
			node.setAttribute('role', 'img');
			node.setAttribute('aria-label', tex);
			node.dataset.done = '1';
		}
	});
</script>

<div class="segs" bind:this={el}>
	{#each segments as seg, i (i)}
		{#if seg.kind === 'text'}
			<div class="md">{@html seg.html || ''}</div>
		{:else if seg.kind === 'fig' && seg.url}
			<figure class="fig">
				{#if zoomable}
					<button type="button" class="figbtn" onclick={() => (zoom = withBust(seg.url))} aria-label="View figure larger">
						<img src={withBust(seg.url)} alt="Question figure" loading="lazy" />
					</button>
				{:else}
					<img src={withBust(seg.url)} alt="Question figure" loading="lazy" />
				{/if}
			</figure>
		{:else if seg.kind === 'table'}
			<div class="pl-table-wrap">
				<table class="pl-table">
					<thead>
						<tr>
							{#each seg.header as cell, hi (hi)}
								<th>
									{#if cell.kind === 'fig'}
										<img src={withBust(cell.url)} alt="Table figure" loading="lazy" />
									{:else}
										{@html cell.html || ''}
									{/if}
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each seg.rows as row, r (r)}
							<tr>
								{#each row as cell, c (c)}
									<td>
										{#if cell.kind === 'fig'}
											<img src={withBust(cell.url)} alt="Table figure" loading="lazy" />
										{:else}
											{@html cell.html || ''}
										{/if}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/each}
</div>

{#if zoomable && zoom}
	<div class="lightbox" onclick={closeZoom} role="dialog" aria-modal="true" aria-label="Enlarged figure">
		<img src={zoom} alt="Enlarged figure" />
	</div>
{/if}
<svelte:window onkeydown={(e) => { if (zoomable && e.key === 'Escape') closeZoom(); }} />

<style>
	.segs {
		min-width: 0;
	}
	.md :global(p) {
		margin: 0.5em 0;
	}
	.md :global(p:first-child) {
		margin-top: 0;
	}
	.md :global(.pl-math-block) {
		display: block;
		text-align: center;
		margin: 0.75em 0;
	}
	.fig {
		margin: 18px 0 22px;
		text-align: center;
	}
	.fig img,
	.pl-table img {
		width: auto;
		max-width: min(400px, 100%);
		height: auto;
		object-fit: contain;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		background: var(--pl-surface);
	}
	.figbtn {
		border: none;
		background: none;
		padding: 0;
		cursor: zoom-in;
		min-height: 0;
		display: inline-block;
	}
	.lightbox {
		position: fixed;
		inset: 0;
		z-index: 60;
		background: rgb(0 0 0 / 0.72);
		display: grid;
		place-items: center;
		padding: 24px;
		cursor: zoom-out;
	}
	.lightbox img {
		max-width: min(1100px, 94vw);
		max-height: 92dvh;
		object-fit: contain;
		background: #fff;
		border-radius: var(--pl-radius-sm);
	}
</style>
