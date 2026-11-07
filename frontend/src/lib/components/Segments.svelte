<script>
	import katex from 'katex';
	import 'katex/dist/katex.min.css';

	/**
	 * Renders backend segments. Text/table cells arrive as HTML with math
	 * placeholders (<span class="pl-math[data-tex]">) produced by the exact
	 * Streamlit splitting rules; this component only fills them with KaTeX.
	 */
	let { segments = [], bust = '', zoomable = false, eager = false, bare = false, scaleBadge = false } = $props();

	/** Click-to-zoom lightbox. Opt-in (zoomable) so existing uses are unaffected. */

	let el = $state(null);
	let zoom = $state(null);

	const GREEK = { alpha: 'alpha', beta: 'beta', gamma: 'gamma', delta: 'delta', epsilon: 'epsilon', varepsilon: 'epsilon', zeta: 'zeta', eta: 'eta', theta: 'theta', lambda: 'lambda', mu: 'mu', nu: 'nu', xi: 'xi', pi: 'pi', rho: 'rho', sigma: 'sigma', tau: 'tau', phi: 'phi', varphi: 'phi', chi: 'chi', psi: 'psi', omega: 'omega', Gamma: 'capital gamma', Delta: 'capital delta', Theta: 'capital theta', Lambda: 'capital lambda', Xi: 'capital xi', Pi: 'capital pi', Sigma: 'capital sigma', Phi: 'capital phi', Psi: 'capital psi', Omega: 'ohm' };
	const WORDS = { times: 'times', cdot: 'dot', pm: 'plus or minus', mp: 'minus or plus', leq: 'less than or equal to', geq: 'greater than or equal to', le: 'less than or equal to', ge: 'greater than or equal to', neq: 'not equal to', ne: 'not equal to', approx: 'approximately', equiv: 'equivalent to', sim: 'similar to', propto: 'proportional to', infty: 'infinity', partial: 'partial', nabla: 'nabla', ldots: 'dot dot dot', cdots: 'dot dot dot', to: 'to', rightarrow: 'goes to', leftarrow: 'comes from', Rightarrow: 'implies', Leftrightarrow: 'if and only if', in: 'in', cup: 'union', cap: 'intersection', sum: 'sum', prod: 'product', int: 'integral', lim: 'limit', log: 'log', ln: 'natural log', sin: 'sine', cos: 'cosine', tan: 'tangent', exp: 'exponential', det: 'determinant', prime: 'prime', percent: 'percent', quad: '', qquad: '', hspace: '', vspace: '', left: '', right: '', big: '', Big: '', bigg: '', Bigg: '', ',': '', ';': '', '!': '', text: '' };

	function extractBrace(s, i) {
		let depth = 0;
		for (let j = i; j < s.length; j++) {
			if (s[j] === '{') depth++;
			else if (s[j] === '}') {
				depth--;
				if (!depth) return [s.slice(i + 1, j), j + 1];
			}
		}
		return [s.slice(i + 1), s.length];
	}

	/** Best-effort plain-language reading of TeX for screen readers. MathML carries the precise form. */
	function spokenMath(tex) {
		let s = String(tex);
		let out = '';
		let i = 0;
		const skipSpaces = () => {
			while (s[i] === ' ') i++;
		};
		const readArg = () => {
			skipSpaces();
			if (s[i] === '{') {
				const [v, j] = extractBrace(s, i);
				i = j;
				return spokenMath(v);
			}
			return s[i++] || '';
		};
		while (i < s.length) {
			const ch = s[i];
			if (ch === '\\') {
				const m = /^\\([a-zA-Z]+)/.exec(s.slice(i));
				if (m) {
					const name = m[1];
					i += 1 + name.length;
					if (['frac', 'dfrac', 'tfrac'].includes(name)) {
						out += ` (${readArg()} over ${readArg()}) `;
					} else if (name === 'sqrt') {
						skipSpaces();
						let root = 'square root of ';
						if (s[i] === '[') {
							const k = s.indexOf(']', i);
							root = `${s.slice(i + 1, k)} root of `;
							i = k + 1;
						}
						out += ` ${root}${readArg()} `;
					} else if (['bar', 'hat'].includes(name)) {
						out += ` ${readArg()} hat `;
					} else if (name === 'vec') {
						out += ` ${readArg()} vector `;
					} else if (name === 'dot') {
						out += ` ${readArg()} dot `;
					} else if (name === 'ddot') {
						out += ` ${readArg()} double dot `;
					} else if (name === 'tilde') {
						out += ` ${readArg()} tilde `;
					} else if (['overline', 'underline'].includes(name)) {
						out += ` ${readArg()} `;
					} else if (GREEK[name] !== undefined) {
						out += ` ${GREEK[name]} `;
					} else if (WORDS[name] !== undefined) {
						out += ` ${WORDS[name]} `;
					} else {
						out += ` ${name} `;
					}
					continue;
				}
				// spacing / escaped chars: \, \: \; \! \  \% \& \$
				const esc = s[i + 1];
				i += 2;
				if (esc === '%') out += ' percent ';
				else if (esc === '&') out += ' and ';
				else out += ' ';
				continue;
			}
			if (ch === '_') {
				i++;
				out += ` sub ${readArg()} `;
				continue;
			}
			if (ch === '^') {
				i++;
				out += ` to the power of ${readArg()} `;
				continue;
			}
			if (ch === '{' || ch === '}') {
				i++;
				out += ' ';
				continue;
			}
			if (ch === '&') {
				i++;
				out += ' and ';
				continue;
			}
			if (/[a-zA-Z0-9]/.test(ch)) {
				let j = i;
				while (j < s.length && /[a-zA-Z0-9]/.test(s[j])) j++;
				out += ` ${s.slice(i, j)} `;
				i = j;
				continue;
			}
			if (ch === '-') out += ' minus ';
			else if (ch === '+') out += ' plus ';
			else if (ch === '=') out += ' equals ';
			else if (ch === '*') out += ' times ';
			else if (ch === "'") out += ' prime ';
			else if (ch === '|') out += ' absolute value of ';
			i++;
		}
		return out.replace(/\s+/g, ' ').trim().slice(0, 240);
	}

	function withBust(url) {
		return bust && url.startsWith('/api/') ? `${url}?v=${bust}` : url;
	}

	function closeZoom() {
		zoom = null;
	}

	/**
	 * Live rendered-size badge for sheet figures: shows the displayed size
	 * as a percent of the natural size, amber below 50% (labels at risk).
	 * Screen-only — print CSS hides .figscale. No-op unless enabled.
	 */
	function figbadge(node, enabled) {
		if (!enabled) return;
		const fig = node.closest('figure');
		if (!fig) return;
		const badge = document.createElement('span');
		badge.className = 'figscale';
		badge.hidden = true;
		fig.appendChild(badge);
		const update = () => {
			const nat = node.naturalWidth;
			if (!nat) return;
			// getBoundingClientRect: layout width even mid-settle; clientWidth
			// can lie if measured before caps apply.
			const w = Math.round(node.getBoundingClientRect().width);
			if (w <= 0) return;
			const pct = Math.round((w / nat) * 100);
			badge.textContent = `${pct}%`;
			badge.title = `Shown ${w}px of ${nat}px natural`;
			badge.classList.toggle('warn', pct < 50);
			badge.hidden = false;
		};
		node.addEventListener('load', update);
		let ro = null;
		try {
			ro = new ResizeObserver(update);
			ro.observe(node);
		} catch { /* ignore */ }
		update();
		// One delayed pass: catches any early measure taken before layout,
		// fonts or the sheet scale settled. Idempotent — never loops.
		const late = setTimeout(update, 1200);
		return {
			destroy() {
				clearTimeout(late);
				try {
					ro?.disconnect();
				} catch { /* ignore */ }
				node.removeEventListener('load', update);
				badge.remove();
			}
		};
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
			node.setAttribute('aria-label', spokenMath(tex) || 'mathematical expression');
			node.dataset.done = '1';
		}
	});
</script>

<div class="segs" class:bare bind:this={el}>
	{#each segments as seg, i (i)}
		{#if seg.kind === 'text'}
			<div class="md">{@html seg.html || ''}</div>
		{:else if seg.kind === 'fig' && seg.url}
			<figure class="fig">
				{#if zoomable}
					<button type="button" class="figbtn" onclick={() => (zoom = withBust(seg.url))} aria-label="View figure larger">
						<img src={withBust(seg.url)} alt="Question figure" loading={eager ? "eager" : "lazy"} use:figbadge={scaleBadge} />
					</button>
				{:else}
					<img src={withBust(seg.url)} alt="Question figure" loading={eager ? "eager" : "lazy"} use:figbadge={scaleBadge} />
				{/if}
			</figure>
		{:else if seg.kind === 'table'}
			<div class="pl-table-wrap">
				<table class="pl-table">
					<thead>
						<tr>
							{#each seg.header as cell, hi (hi)}
								<th>
									{#each cell as item, hii (hii)}
										{#if item.kind === 'fig'}
											<img src={withBust(item.url)} alt="Table figure" loading={eager ? "eager" : "lazy"} />
										{:else}
											{@html item.html || ''}
										{/if}
									{/each}
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each seg.rows as row, r (r)}
							<tr>
								{#each row as cell, c (c)}
									<td>
										{#each cell as item, ci (ci)}
											{#if item.kind === 'fig'}
												<img src={withBust(item.url)} alt="Table figure" loading={eager ? "eager" : "lazy"} />
											{:else}
												{@html item.html || ''}
											{/if}
										{/each}
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
		position: relative;
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
	/* Bare sheets (builder previews + print): images float on the paper
	   with no boxes — matches the original paper look. */
	.segs.bare .fig img,
	.segs.bare .pl-table img {
		border: none;
		border-radius: 0;
		background: none;
	}
	.figscale {
		position: absolute;
		top: 4px;
		right: 4px;
		font-size: 0.65rem;
		font-weight: 700;
		line-height: 1.4;
		background: rgb(0 0 0 / 0.55);
		color: #fff;
		border-radius: 6px;
		padding: 1px 7px;
		pointer-events: none;
		white-space: nowrap;
	}
	.figscale.warn {
		background: var(--pl-ochre);
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
