<script>
	/**
	 * Live Answer Sheet: page 1 = generated key (editable, auto-filled
	 * from filed answers, manual overrides win), page 2+ = detailed
	 * solutions. Same generated numbers throughout. Pure render of the
	 * shared numbering map — editing happens through the same store the
	 * editor writes, so no state is duplicated.
	 */
	import KeyTable from '$lib/components/KeyTable.svelte';
	import SolutionsList from '$lib/components/SolutionsList.svelte';

	let { title = '', numbering, blocks = {}, overrides = {}, parsed = {}, ordered = [], onOverride } = $props();
</script>

<div class="sheet" aria-label="Answer key">
	<header class="dochead">
		<h2>{title?.trim() || 'Untitled paper'} — Answer key</h2>
	</header>
	<KeyTable {numbering} {blocks} {overrides} {parsed} {onOverride} />
</div>

<div class="sheet solspage" aria-label="Detailed solutions">
	<SolutionsList {ordered} {numbering} />
</div>

<style>
	.sheet {
		font-size: 0.8125rem;
		line-height: 1.6;
		background: #ffffff;
		color: #111111;
		border: 1px solid var(--pl-line);
		border-radius: 2px;
		box-shadow: var(--pl-shadow-md);
		padding: 44px 52px;
		width: 100%;
		max-width: 794px;
		margin: 0 auto;
	}
	.sheet + .sheet {
		margin-top: 20px;
	}
	.dochead {
		text-align: center;
		border-bottom: 2px solid var(--pl-ink);
		padding-bottom: 12px;
		margin-bottom: 16px;
	}
	.dochead h2 {
		font-family: var(--pl-font-display);
		font-size: 1.25rem;
		margin: 0;
	}
	.sheet :global(.fig) {
		margin: 12px 0 14px;
	}
	.sheet :global(.fig img) {
		max-width: 250px;
	}
	.sheet :global(.pl-table img) {
		max-width: 200px;
	}
	.sheet :global(.key h3),
	.sheet :global(.sols h3) {
		font-family: var(--pl-font-display);
		font-size: 1.2rem;
	}
	@media print {
		.sheet {
			box-shadow: none;
			border: none;
			border-radius: 0;
			max-width: none;
			margin: 0;
			padding: 0;
		}
		.sheet + .sheet {
			margin-top: 0;
		}
		.solspage {
			break-before: page;
		}
	}
</style>
