<script>
	import '../app.css';
	import '@fontsource/inter/400.css';
	import '@fontsource/inter/500.css';
	import '@fontsource/inter/600.css';
	import '@fontsource/inter/700.css';
	import '@fontsource/source-serif-4/400.css';
	import '@fontsource/source-serif-4/600.css';
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import Topbar from '$lib/components/Topbar.svelte';
	import Toasts from '$lib/components/Toasts.svelte';
	import { theme, refreshStatus, appStatus } from '$lib/stores.js';

	let { children } = $props();
	// The split view keeps a bare workspace for two full-height columns.
	const isFocus = $derived($page.url.pathname === '/search/side');

	$effect(() => {
		document.documentElement.dataset.theme = $theme;
	});

	onMount(() => {
		refreshStatus();
		// Fast while something is moving (index build, queue), slow otherwise.
		let timer;
		const tick = async () => {
			await refreshStatus();
			const s = $appStatus;
			const busy = s?.index?.building || (s?.jobs?.running ?? 0) > 0 || (!s?.queue?.paused && (s?.jobs?.queued ?? 0) > 0);
			timer = setTimeout(tick, busy ? 2000 : 6000);
		};
		timer = setTimeout(tick, 2000);
		return () => clearTimeout(timer);
	});
</script>

{#if isFocus}
	<div class="focusshell">
		{@render children()}
	</div>
{:else}
	<div class="shell">
		<Sidebar />
		<div class="main">
			<Topbar />
			<main class="content">
				{@render children()}
			</main>
		</div>
	</div>
{/if}
<Toasts />

<style>
	.shell {
		display: flex;
		min-height: 100dvh;
	}
	.main {
		flex: 1;
		min-width: 0;
		margin-left: 264px;
		display: flex;
		flex-direction: column;
	}
	.content {
		padding: 28px;
		max-width: 1180px;
		width: 100%;
		margin: 0 auto;
	}
	.focusshell {
		height: 100dvh;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	@media (max-width: 900px) {
		.main {
			margin-left: 0;
		}
		.content {
			padding: 20px 16px;
		}
		.focusshell {
			height: auto;
			overflow: visible;
		}
	}
</style>
