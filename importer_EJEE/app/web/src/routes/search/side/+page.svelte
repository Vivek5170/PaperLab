<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import SearchExplorer from '$lib/components/SearchExplorer.svelte';

	// Two comfortable columns need a wide screen; phones use the normal list.
	let wide = $state(null);

	onMount(() => {
		wide = !window.matchMedia('(max-width: 900px)').matches;
		if (!wide) goto('/search', { replaceState: true });
	});
</script>

<svelte:head><title>Search EJEE · Side view - EJEE Importer</title></svelte:head>

{#if wide}
	<SearchExplorer lockSide />
{/if}
