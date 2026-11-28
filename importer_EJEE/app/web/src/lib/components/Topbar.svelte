<script>
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { theme, sidebarOpen, appStatus } from '$lib/stores.js';

	const onSearch = $derived($page.url.pathname === '/search');
	const crumb = $derived(
		{
			search: 'Search',
			item: 'Question',
			books: 'Convert Books',
			cart: 'Cart',
			process: 'Process & Publish',
			settings: 'Settings'
		}[$page.url.pathname.split('/')[1]] ?? 'Search'
	);
</script>

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
		<span>EJEE</span>
		<span class="sep" aria-hidden="true">/</span>
		<span class="current">{crumb}</span>
	</nav>

	<div class="actions">
		{#if $appStatus?.cart}
			<a class="role-pill" href="/cart">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<circle cx="9" cy="20" r="1.6" /><circle cx="17" cy="20" r="1.6" /><path d="M3 3h2l2.4 12.2a1 1 0 0 0 1 .8h8.7a1 1 0 0 0 1-.8L20 7H6" />
				</svg>
				{$appStatus.cart} part{$appStatus.cart === 1 ? '' : 's'}
			</a>
		{/if}
		{#if onSearch}
			<button
				type="button"
				class="icon-btn sidebtn"
				aria-label="Open side-by-side reader"
				title="Side-by-side reader"
				onclick={() => goto('/search/side')}
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
		text-decoration: none;
		white-space: nowrap;
	}
	.role-pill:hover {
		background: var(--pl-raised);
	}
	.role-pill svg {
		width: 16px;
		height: 16px;
		flex-shrink: 0;
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
	.icon-btn svg {
		width: 22px;
		height: 22px;
	}
	.hamburger {
		display: none;
	}
	@media (max-width: 900px) {
		.topbar {
			padding: 10px 14px;
		}
		.hamburger {
			display: grid;
		}
		.sidebtn {
			display: none;
		}
		.crumbs {
			display: none;
		}
	}
</style>
