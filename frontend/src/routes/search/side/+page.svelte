<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import SearchExplorer from '$lib/components/SearchExplorer.svelte';

	// Side view needs two comfortable columns — keep it off phones and
	// other narrow viewports where it cannot work, instead of shipping a
	// cramped fallback.
	let wide = $state(null);

	onMount(() => {
		wide = !window.matchMedia('(max-width: 900px)').matches;
		if (!wide) goto('/search', { replaceState: true });
	});
</script>

<svelte:head><title>Search questions · Side view - PaperLab</title></svelte:head>

{#if wide}
	<SearchExplorer lockSide />
{/if}
