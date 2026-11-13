<script>
	import '../app.css';
	// Bundled webfonts (Fontsource, OFL): zero-apt, deterministic on bare
	// Ubuntu / phones / print. Each ships its own woff2 via Vite.
	import '@fontsource/inter/400.css';
	import '@fontsource/inter/500.css';
	import '@fontsource/inter/600.css';
	import '@fontsource/inter/700.css';
	import '@fontsource/inter/400-italic.css';
	import '@fontsource/source-serif-4/400.css';
	import '@fontsource/source-serif-4/600.css';
	import '@fontsource/tinos/400.css';
	import '@fontsource/tinos/700.css';
	import '@fontsource/tinos/400-italic.css';
	import '@fontsource/tinos/700-italic.css';
	import '@fontsource/arimo/400.css';
	import '@fontsource/arimo/700.css';
	import '@fontsource/arimo/400-italic.css';
	import '@fontsource/arimo/700-italic.css';
	import '@fontsource/caladea/400.css';
	import '@fontsource/caladea/700.css';
	import '@fontsource/caladea/400-italic.css';
	import '@fontsource/caladea/700-italic.css';
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import Topbar from '$lib/components/Topbar.svelte';
	import LoginDialog from '$lib/components/LoginDialog.svelte';
	import { inboxItems, inboxList, role, theme } from '$lib/stores.js';
	import { api } from '$lib/api.js';

	let { children } = $props();
	let counts = $state({ done: 0, queued: 0, running: 0, failed: 0 });
	const inboxCount = $derived($inboxItems?.length ?? 0);
	// Experimental fullscreen workspaces (e.g. /lab/...) render bare chrome.
	const isLab = $derived($page.url.pathname.startsWith('/lab'));
	// Full-bleed workspace routes fill the shell instead of the narrow column.
	const isWide = $derived($page.url.pathname === '/builder');
	// Focus pages (e.g. the search split view) keep the topbar but drop the
	// sidebar so the workspace gets the full width, like the lab editor.
	const isFocus = $derived($page.url.pathname === '/search/side');

	$effect(() => {
		document.documentElement.dataset.theme = $theme;
	});

	onMount(async () => {
		// Independent shell fetches run together; each degrades on its own
		// so the shell still renders when the backend is offline.
		const [meRes, sumRes, inboxRes] = await Promise.all([
			api.me().catch(() => null),
			api.getLibrarySummary().catch(() => null),
			api.getInbox().catch(() => null)
		]);
		try {
			role.set(meRes?.authed ? 'archivist' : 'student');
		} catch {
			/* backend offline: stay in student view */
		}
		try {
			counts = {
				done: sumRes?.buckets?.done ?? 0,
				queued: sumRes?.buckets?.queued ?? 0,
				running: sumRes?.buckets?.running ?? 0,
				failed: sumRes?.buckets?.failed ?? 0
			};
		} catch {
			/* backend offline: shell still renders */
		}
		try {
			inboxItems.set(inboxList(inboxRes));
		} catch {
			/* students / offline: no badge */
		}
	});
</script>

{#if isLab}
	<div class="labshell">
		{@render children()}
		<LoginDialog />
	</div>
{:else if isFocus}
	<div class="focusshell">
		{@render children()}
		<LoginDialog />
	</div>
{:else}
	<div class="shell" class:wide={isWide}>
		<Sidebar {counts} {inboxCount} />
		<div class="main">
			<Topbar crumbs={['Physics']} />
			<main class="content" class:wide={isWide}>
				{@render children()}
			</main>
		</div>
		<LoginDialog />
	</div>
{/if}

<style>
	.shell {
		display: flex;
		min-height: 100dvh;
	}
	.main {
		flex: 1;
		min-width: 0;
		min-height: 0;
		margin-left: 264px;
		display: flex;
		flex-direction: column;
	}
	.focusshell {
		height: 100dvh;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	@media (max-width: 900px) {
		.focusshell {
			height: auto;
			overflow: visible;
		}
	}
	.content {
		padding: 28px;
		max-width: 1120px;
		width: 100%;
		margin: 0 auto;
	}
	.shell.wide {
		height: 100dvh;
		overflow: hidden;
	}
	.content.wide {
		padding: 0;
		max-width: none;
		margin: 0;
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.labshell {
		min-height: 100dvh;
		display: flex;
		flex-direction: column;
	}
	@media (max-width: 900px) {
		.main {
			margin-left: 0;
		}
		.shell.wide {
			height: auto;
			overflow: visible;
		}
	}
	@media print {
		.shell.wide {
			height: auto;
			overflow: visible;
			display: block;
		}
		.shell.wide :global(.sidebar),
		.shell.wide :global(.topbar) {
			display: none;
		}
		.shell.wide .main {
			margin-left: 0;
		}
		.shell.wide .content.wide {
			display: block;
			overflow: visible;
		}
	}
</style>
