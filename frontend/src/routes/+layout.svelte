<script>
	import '../app.css';
	import { onMount } from 'svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import Topbar from '$lib/components/Topbar.svelte';
	import LoginDialog from '$lib/components/LoginDialog.svelte';
	import { inboxItems, inboxList, role, theme } from '$lib/stores.js';
	import { api } from '$lib/api.js';

	let { children } = $props();
	let counts = $state({ done: 0, queued: 0, running: 0, failed: 0 });
	const inboxCount = $derived($inboxItems?.length ?? 0);

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

<div class="shell">
	<Sidebar {counts} {inboxCount} />
	<div class="main">
		<Topbar crumbs={['Physics']} />
		<main class="content">
			{@render children()}
		</main>
	</div>
	<LoginDialog />
</div>

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
		max-width: 1120px;
		width: 100%;
		margin: 0 auto;
	}
	@media (max-width: 900px) {
		.main {
			margin-left: 0;
		}
	}
</style>
