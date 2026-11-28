<script>
	import { page } from '$app/stores';
	import ItemReader from '$lib/components/ItemReader.svelte';

	const source = $derived($page.url.searchParams.get('source') ?? '');
	const key = $derived($page.url.searchParams.get('key') ?? '');
</script>

<svelte:head><title>Question - EJEE Importer</title></svelte:head>

<div class="wrap">
	<a class="back" href="/search" onclick={(e) => { if (history.length > 1) { e.preventDefault(); history.back(); } }}>← Back to search</a>
	{#if source && key}
		{#key `${source}|${key}`}
			<ItemReader {source} itemKey={key} />
		{/key}
	{:else}
		<p class="pl-error">No item selected.</p>
	{/if}
</div>

<style>
	.wrap {
		max-width: 860px;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		gap: 16px;
	}
	.back {
		font-weight: 600;
		font-size: 0.85rem;
	}
</style>
