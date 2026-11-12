<script>
	/**
	 * Topic tree dropdown: Module → Chapter → Week → Subtopic checkboxes
	 * with checked / unchecked / indeterminate states. Checking a parent
	 * selects it plus every descendant (backend expands union); unchecking
	 * one child keeps its siblings. Selection is an explicit code list.
	 */
	let { nodes = [], counts = {}, selected = $bindable([]), mode = 'filter', label = 'Topics' } = $props();
	// mode 'filter' (search): checking a parent selects it plus every
	// descendant. mode 'tag' (classify/inbox): only subtopics are
	// selectable (parents just expand); checking one tags exactly it.

	let open = $state(false);
	let q = $state('');
	let panel = $state(null);
	let expanded = $state([]);

	const inSel = (code) => selected.includes(code);

	const byParent = $derived.by(() => {
		const m = new Map();
		for (const n of nodes) {
			const k = n.parent ?? '';
			if (!m.has(k)) m.set(k, []);
			m.get(k).push(n);
		}
		return m;
	});
	const roots = $derived(byParent.get('') ?? []);

	function descendants(node) {
		const out = [];
		const stack = [...(byParent.get(node.code) ?? [])];
		while (stack.length) {
			const c = stack.pop();
			out.push(c.code);
			stack.push(...(byParent.get(c.code) ?? []));
		}
		return out;
	}

	function collect(node) {
		return [node.code, ...descendants(node)];
	}

	function stateOf(node) {
		const codes = collect(node);
		const n = codes.filter(inSel).length;
		if (n === codes.length) return 'on';
		if (n > 0) return 'part';
		return 'off';
	}

	function toggle(node) {
		if (mode === 'tag') {
			// Only subtopics are taggable; parents expand but never select.
			if (node.level !== 'subtopic') return;
			selected = inSel(node.code)
				? selected.filter((c) => c !== node.code)
				: [...selected, node.code];
			return;
		}
		const codes = collect(node);
		if (stateOf(node) === 'on') {
			const drop = new Set(codes);
			selected = selected.filter((c) => !drop.has(c));
		} else {
			const have = new Set(selected);
			for (const c of codes) have.add(c);
			selected = [...have];
		}
	}

	function aggCount(node) {
		// Facets carry distinct-question counts per subtree root, so a
		// question with two tags under one module counts once here --
		// matching the result list exactly.
		return counts[node.code] ?? 0;
	}

	function indet(el, val) {
		el.indeterminate = !!val;
		return { update(v) { el.indeterminate = !!v; } };
	}

	function toggleExpand(code) {
		expanded = expanded.includes(code)
			? expanded.filter((c) => c !== code)
			: [...expanded, code];
	}

	const isOpen = (code) => expanded.includes(code);

	const matches = $derived(
		!q.trim()
			? []
			: nodes
					.filter((n) => n.level === 'subtopic' && `${n.code} ${n.name}`.toLowerCase().includes(q.trim().toLowerCase()))
					.slice(0, 60)
	);

	const selCount = $derived(selected.length);

	function close() {
		open = false;
	}
</script>

<svelte:window
	onclick={(e) => {
		if (open && panel && !panel.contains(e.target)) close();
	}}
	onkeydown={(e) => {
		if (e.key === 'Escape') close();
	}}
/>

<div class="dd" class:tag={mode === 'tag'} bind:this={panel}>
	{#if mode === 'tag' && selected.length > 0}
		<div class="sel-chips" aria-label="Selected topics">
			{#each selected as code (code)}
				{@const picked = nodes.find((n) => n.code === code)}
				<span class="pl-chip" title={code}>
					{picked?.name ?? code}
					<button
						type="button"
						aria-label={`Remove ${picked?.name ?? code}`}
						onclick={() => (selected = selected.filter((c) => c !== code))}
					>
						×
					</button>
				</span>
			{/each}
		</div>
	{/if}
	<button
		type="button"
		class="dd-btn"
		class:active={selCount > 0}
		aria-expanded={open}
		aria-haspopup="tree"
		onclick={() => (open = !open)}
	>
		<span class="dd-label">{label}{selCount > 0 ? ` · ${selCount}` : ''}</span>
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
	</button>
	{#if open}
		<div class="dd-panel tree-panel">
			<div class="tree-search">
				<input
					type="search"
					bind:value={q}
					placeholder="Find a subtopic…"
					aria-label="Find a subtopic"
				/>
			</div>
			{#if q.trim()}
				<ul class="tree-list">
					{#each matches as m (m.code)}
						<li>
							<label class="row leaf">
								<input type="checkbox" checked={inSel(m.code)} onchange={() => toggle(m)} />
								<span class="nm">{m.name}</span>
								{#if (counts[m.code] ?? 0) > 0}
									<span class="ct pl-mono">{counts[m.code]}</span>
								{/if}
							</label>
						</li>
					{/each}
					{#if matches.length === 0}
						<li><p class="dd-empty">No subtopics match.</p></li>
					{/if}
				</ul>
			{:else}
				<ul class="tree-list">
					{#each roots as mod (mod.code)}
						{@render branch(mod, 0)}
					{/each}
				</ul>
			{/if}
			<div class="dd-foot">
				<span class="hint">{selCount} selected</span>
				<button type="button" class="dd-clear" disabled={selCount === 0} onclick={() => (selected = [])}>
					Clear
				</button>
			</div>
		</div>
	{/if}
</div>

{#snippet branch(node, depth)}
	{@const kids = byParent.get(node.code) ?? []}
	{@const st = stateOf(node)}
	{@const open = isOpen(node.code)}
	<li>
		<div class="row" style={`--d: ${depth}`}>
			{#if kids.length}
				<button
					type="button"
					class="chev"
					aria-expanded={open}
					aria-label={`${open ? 'Collapse' : 'Expand'} ${node.name}`}
					onclick={() => toggleExpand(node.code)}
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d={open ? 'm6 9 6 6 6-6' : 'm9 6 6 6-6 6'} /></svg>
				</button>
				{#if mode === 'tag'}
					<button
						type="button"
						class="nm-btn"
						aria-expanded={open}
						onclick={() => toggleExpand(node.code)}
					>
						<span class="nm">{node.name}</span>
					</button>
				{:else}
					<input
						type="checkbox"
						class="box"
						checked={st === 'on'}
						use:indet={st === 'part'}
						aria-label={`Select ${node.name} and all its subtopics`}
						onchange={() => toggle(node)}
					/>
					<button
						type="button"
						class="nm-btn"
						aria-expanded={open}
						onclick={() => toggleExpand(node.code)}
					>
						<span class="nm">{node.name}</span>
					</button>
				{/if}
				{#if aggCount(node) > 0}
					<span class="ct pl-mono">{aggCount(node)}</span>
				{/if}
			{:else}
				<span class="chev-sp"></span>
				<label class="lbl">
					<input type="checkbox" checked={inSel(node.code)} onchange={() => toggle(node)} />
					<span class="nm">{node.name}</span>
					{#if aggCount(node) > 0}
						<span class="ct pl-mono">{aggCount(node)}</span>
					{/if}
				</label>
			{/if}
		</div>
		{#if kids.length && open}
			<ul>
				{#each kids as k (k.code)}
					{@render branch(k, depth + 1)}
				{/each}
			</ul>
		{/if}
	</li>
{/snippet}

<style>
	.dd {
		position: relative;
	}
	.dd.tag {
		width: 100%;
	}
	.dd.tag .dd-btn {
		width: 100%;
		justify-content: space-between;
		border-radius: var(--pl-radius-sm);
		background: var(--pl-surface);
		color: var(--pl-ink);
		font-weight: 400;
		font-size: 1rem;
		padding: 10px 12px;
		min-height: 44px;
	}
	.dd.tag .tree-panel {
		width: 100%;
		max-height: 300px;
	}
	.sel-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-bottom: 8px;
	}
	.sel-chips .pl-chip button {
		border: none;
		background: none;
		cursor: pointer;
		font-size: 1rem;
		line-height: 1;
		min-height: 0;
		padding: 0 0 0 4px;
	}
	.dd-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		background: var(--pl-surface);
		color: var(--pl-ink-soft);
		font-weight: 600;
		font-size: 0.82rem;
		padding: 8px 14px;
		min-height: 40px;
		white-space: nowrap;
	}
	.dd-btn:hover {
		background: var(--pl-raised);
		color: var(--pl-ink);
	}
	.dd-btn.active {
		background: var(--pl-seal-soft);
		border-color: var(--pl-seal);
		color: var(--pl-ink);
	}
	.dd-btn svg {
		width: 14px;
		height: 14px;
		flex-shrink: 0;
	}
	.dd-panel {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 50;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		box-shadow: var(--pl-shadow-md);
	}
	.tree-panel {
		width: min(380px, 90vw);
		display: flex;
		flex-direction: column;
		max-height: 420px;
	}
	.tree-search {
		padding: 6px;
		border-bottom: 1px solid var(--pl-line);
	}
	.tree-search input {
		width: 100%;
		min-height: 32px;
	}
	.tree-list {
		list-style: none;
		margin: 0;
		padding: 4px;
		overflow-y: auto;
	}
	.tree-list ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 4px 4px 4px calc(4px + var(--d, 0) * 16px);
		border-radius: var(--pl-radius-sm);
	}
	.row:hover {
		background: var(--pl-raised);
	}
	.row.leaf {
		padding: 4px 8px;
		gap: 8px;
		cursor: pointer;
	}
	.chev {
		border: none;
		background: none;
		padding: 0;
		min-height: 28px;
		min-width: 28px;
		color: var(--pl-ink-soft);
		display: grid;
		place-items: center;
		flex-shrink: 0;
	}
	.chev svg {
		width: 16px;
		height: 16px;
	}
	.chev-sp {
		width: 28px;
		flex-shrink: 0;
	}
	.box {
		accent-color: var(--pl-seal);
		width: 16px;
		height: 16px;
		flex-shrink: 0;
		min-height: 0;
		margin: 0;
	}
	.nm-btn {
		flex: 1;
		min-width: 0;
		border: none;
		background: none;
		text-align: left;
		padding: 3px 4px;
		min-height: 28px;
		font-size: 0.85rem;
		overflow: hidden;
	}
	.nm-btn .nm {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.lbl {
		display: flex;
		align-items: center;
		gap: 8px;
		flex: 1;
		min-width: 0;
		cursor: pointer;
		margin: 0;
		padding: 2px 4px;
		font-weight: 500;
	}
	.lbl input,
	.row.leaf input {
		accent-color: var(--pl-seal);
		width: 16px;
		height: 16px;
		flex-shrink: 0;
		min-height: 0;
		margin: 0;
	}
	.nm {
		flex: 1;
		min-width: 0;
		font-size: 0.85rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.ct {
		color: var(--pl-ink-soft);
		font-size: 0.75rem;
		flex-shrink: 0;
	}
	.dd-empty {
		margin: 0;
		padding: 14px;
		color: var(--pl-ink-soft);
		font-size: 0.85rem;
	}
	.dd-foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		border-top: 1px solid var(--pl-line);
		padding: 4px 6px 4px 12px;
	}
	.hint {
		font-size: 0.78rem;
		color: var(--pl-ink-soft);
	}
	.dd-clear {
		border: none;
		background: none;
		color: var(--pl-seal);
		font-weight: 600;
		font-size: 0.82rem;
		padding: 6px 10px;
		min-height: 32px;
	}
	.dd-clear:disabled {
		color: var(--pl-ink-soft);
		opacity: 0.5;
		cursor: default;
	}
</style>
