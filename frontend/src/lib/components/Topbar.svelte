<script>
	import { page } from '$app/stores';
	import { role, searchQuery, theme, loginOpen, sidebarOpen, searchSide } from '$lib/stores.js';
	import { api } from '$lib/api.js';

	let { crumbs = [] } = $props();

	const isArchivist = $derived($role === 'archivist');
	const onArchive = $derived($page.url.pathname.startsWith('/archive'));
	const onSearch = $derived($page.url.pathname === '/search');

	function onKeydown(event) {
		if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
			if (!onArchive) return;
			event.preventDefault();
			document.getElementById('global-search')?.focus();
		}
	}

	async function toggleRole() {
		if ($role === 'archivist') {
			await api.logout().catch(() => {});
			role.set('student');
		} else {
			loginOpen.set(true);
		}
	}
</script>

<svelte:window onkeydown={onKeydown} />

<header class="topbar">
	<button
		type="button"
		class="icon-btn hamburger"
		aria-label="Open navigation"
		aria-expanded={$sidebarOpen}
		onclick={() => sidebarOpen.set(true)}
	>
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
			<path d="M4 7h16M4 12h16M4 17h16" />
		</svg>
	</button>
	<nav class="crumbs" aria-label="Breadcrumb">
		{#each crumbs as crumb, i (crumb)}
			{#if i > 0}<span class="sep" aria-hidden="true">/</span>{/if}
			<span class:current={i === crumbs.length - 1}>{crumb}</span>
		{/each}
	</nav>

	<div class="actions">
		<button type="button" class="role-pill" onclick={toggleRole} title="Switch role">
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
				<path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
			</svg>
			{isArchivist ? 'Archivist' : 'Student'}
		</button>

		{#if onArchive}
		<div class="search">
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
				<circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
			</svg>
			<input
				id="global-search"
				type="search"
				placeholder="Search"
				bind:value={$searchQuery}
				aria-label="Search papers"
			/>
			<kbd>Ctrl K</kbd>
		</div>
		{/if}

		{#if onSearch}
			<button
				type="button"
				class="icon-btn"
				class:active={$searchSide}
				aria-label="Toggle side-by-side reader"
				aria-pressed={$searchSide}
				title="Side-by-side reader"
				onclick={() => searchSide.set(!$searchSide)}
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
					<rect x="3" y="4" width="7" height="16" rx="1.5" /><rect x="14" y="4" width="7" height="16" rx="1.5" />
				</svg>
			</button>
		{/if}

		<button
			type="button"
			class="icon-btn"
			aria-label="Toggle color theme"
			onclick={() => theme.set($theme === 'light' ? 'dark' : 'light')}
		>
			{#if $theme === 'light'}
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
					<circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
				</svg>
			{:else}
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
					<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
				</svg>
			{/if}
		</button>
	</div>
</header>

<style>
	.topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 12px 28px;
		border-bottom: 1px solid var(--pl-line);
		background: var(--pl-paper);
		position: sticky;
		top: 0;
		z-index: 30;
	}
	.crumbs {
		display: flex;
		align-items: center;
		gap: 8px;
		font-weight: 500;
		white-space: nowrap;
	}
	.crumbs .sep,
	.crumbs span:not(.current) {
		color: var(--pl-ink-soft);
	}
	.actions {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.role-pill {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		border-radius: var(--pl-radius-pill);
		border: 1px solid var(--pl-line);
		background: var(--pl-surface);
		padding: 8px 16px;
		font-weight: 600;
		font-size: 0.85rem;
	}
	.role-pill svg {
		width: 16px;
		height: 16px;
	}
	.search {
		display: flex;
		align-items: center;
		gap: 8px;
		background: var(--pl-surface);
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-pill);
		padding: 6px 8px 6px 14px;
	}
	.search svg {
		width: 18px;
		height: 18px;
		color: var(--pl-ink-soft);
		flex-shrink: 0;
	}
	.search input {
		border: none;
		background: none;
		padding: 0;
		min-height: 0;
		width: 140px;
	}
	.search input:focus {
		outline: none;
	}
	.search:focus-within {
		outline: 2px solid var(--pl-focus);
		outline-offset: 2px;
	}
	kbd {
		font-family: var(--pl-font-mono);
		font-size: 0.72rem;
		background: var(--pl-raised);
		border-radius: 6px;
		padding: 2px 8px;
		color: var(--pl-ink-soft);
	}
	.icon-btn {
		display: grid;
		place-items: center;
		width: 44px;
		height: 44px;
		min-height: 44px;
		border-radius: 50%;
		border: none;
		background: none;
		color: var(--pl-ink);
	}
	.icon-btn:hover {
		background: var(--pl-raised);
	}
	.icon-btn.active {
		background: var(--pl-raised);
		color: var(--pl-seal);
	}
	.icon-btn svg {
		width: 22px;
		height: 22px;
	}
	.hamburger {
		display: none;
	}
	@media (max-width: 900px) {
		.hamburger {
			display: grid;
		}
		.crumbs {
			display: none;
		}
		.search input {
			width: 80px;
		}
	}
</style>
