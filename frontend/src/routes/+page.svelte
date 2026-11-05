<script>
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	onMount(() => goto('/archive', { replaceState: true }));
</script>

<p class="pl-sub">Loading Archive…</p>
