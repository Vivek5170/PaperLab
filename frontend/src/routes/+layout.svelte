<script>
	import '../app.css';
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

	$effect(() => {
		document.documentElement.dataset.theme = $theme;
	});

	onMount(async () => {
		try {
			const me = await api.me();
			role.set(me.authed ? 'archivist' : 'student');
		} catch {
			/* backend offline: stay in student view */
		}
		try {
			const summary = await api.getLibrarySummary();
			counts = {
				done: summary.buckets?.done ?? 0,
				queued: summary.buckets?.queued ?? 0,
				running: summary.buckets?.running ?? 0,
				failed: summary.buckets?.failed ?? 0
			};
		} catch {
			/* backend offline: shell still renders */
		}
		try {
			inboxItems.set(inboxList(await api.getInbox().catch(() => null)));
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
</style>
