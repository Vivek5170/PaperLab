<script>
	import { marked } from 'marked';
	import katex from 'katex';
	import 'katex/dist/katex.min.css';

	/**
	 * Renders backend TeX segments. Formulas are pre-split so each one gets
	 * role="img" + aria-label with its TeX source (KaTeX ships MathML too).
	 */
	let { segments = [] } = $props();

	const MATH_RE = /\$\$([\s\S]+?)\$\$|(?<!\\)\$([^$\n]+?)\$/g;

	function renderMarkdown(md) {
		const parts = [];
		let last = 0;
		let m;
		MATH_RE.lastIndex = 0;
		while ((m = MATH_RE.exec(md)) !== null) {
			if (m.index > last) parts.push({ t: 'text', v: md.slice(last, m.index) });
			const display = m[1] !== undefined;
			parts.push({ t: 'math', v: (display ? m[1] : m[2]).trim(), display });
			last = m.index + m[0].length;
		}
		if (last < md.length) parts.push({ t: 'text', v: md.slice(last) });
		return parts
			.map((p) => {
				if (p.t === 'text') return marked.parse(p.v || '');
				let html = '';
				try {
					html = katex.renderToString(p.v, {
						displayMode: p.display,
						throwOnError: false
					});
				} catch {
					html = '';
				}
				const safe = p.v.replace(/"/g, '&quot;');
				return `<span class="math" role="img" aria-label="${safe}">${html}</span>`;
			})
			.join('');
	}
</script>

<div class="segs">
	{#each segments as seg, i (i)}
		{#if seg.kind === 'text'}
			<div class="md">{@html renderMarkdown(seg.markdown || '')}</div>
		{:else if seg.kind === 'fig' && seg.url}
			<figure class="fig">
				<img src={seg.url} alt="Question figure" loading="lazy" />
			</figure>
		{:else if seg.kind === 'table'}
			<div class="pl-table-wrap">
				<table class="pl-table">
					<thead>
						<tr>
							{#each seg.header as cell, hi (hi)}
								<th>
									{#if cell.kind === 'fig'}
										<img src={cell.url} alt="Table figure" loading="lazy" />
									{:else}
										{@html renderMarkdown(cell.markdown || '')}
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
											<img src={cell.url} alt="Table figure" loading="lazy" />
										{:else}
											{@html renderMarkdown(cell.markdown || '')}
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
	.md :global(.math) {
		white-space: normal;
	}
	.fig {
		margin: 12px 0;
	}
	.fig img,
	.pl-table img {
		max-width: 400px;
		width: 100%;
		height: auto;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
	}
</style>
