<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';

	onMount(() => goto('/search', { replaceState: true }));
</script>
