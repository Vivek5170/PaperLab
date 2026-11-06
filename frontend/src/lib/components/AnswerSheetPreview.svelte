<script>
	/**
	 * Live Answer Sheet: generated key (editable) + detailed solutions,
	 * same generated numbers as the Question Sheet. Pure render of the
	 * shared numbering map — editing happens through the same store the
	 * editor writes, so no state is duplicated.
	 */
	import KeyTable from '$lib/components/KeyTable.svelte';
	import SolutionsList from '$lib/components/SolutionsList.svelte';

	let { title = '', numbering, blocks = {}, overrides = {}, ordered = [], onOverride } = $props();
</script>

<div class="sheet" aria-label="Answer sheet preview">
	<header class="dochead">
		<h2>{title?.trim() || 'Untitled paper'} — Answers & solutions</h2>
		<p class="pl-sub">{numbering.total} number{numbering.total === 1 ? '' : 's'} · key first, detailed solutions after</p>
	</header>
	<KeyTable {numbering} {blocks} {overrides} {onOverride} />
	<SolutionsList {ordered} {numbering} />
</div>

<style>
	.sheet {
		background: #fffdf9;
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-md);
		box-shadow: var(--pl-shadow-sm);
		padding: 28px 30px;
		width: 100%;
		max-width: 800px;
		margin: 0 auto;
	}
	.dochead {
		text-align: center;
		border-bottom: 2px solid var(--pl-ink);
		padding-bottom: 12px;
		margin-bottom: 16px;
	}
	.dochead h2 {
		font-family: var(--pl-font-display);
		font-size: 1.4rem;
		margin: 0 0 2px;
	}
	.dochead .pl-sub {
		margin: 0;
	}
	.sheet :global(.key h3),
	.sheet :global(.sols h3) {
		font-family: var(--pl-font-display);
		font-size: 1.2rem;
	}
</style>
