<script>
	import { page } from '$app/stores';
	import { appStatus, sidebarOpen } from '$lib/stores.js';

	function close() {
		sidebarOpen.set(false);
	}

	const section = $derived('/' + ($page.url.pathname.split('/')[1] || 'search'));
	const s = $derived($appStatus);
	const missing = $derived(s?.missing?.length ?? 0);
	const jobs = $derived(s?.jobs ?? {});

	const items = $derived([
		{ href: '/search', label: 'Search EJEE', icon: 'search', match: ['/search', '/item'] },
		{ href: '/books', label: 'Convert Books', icon: 'book' },
		{ href: '/cart', label: 'Cart', icon: 'cart', badge: s?.cart || null },
		{
			href: '/process',
			label: 'Process & Publish',
			icon: 'upload',
			badge: jobs.failed || null,
			warn: true
		},
		{ href: '/settings', label: 'Settings', icon: 'gear', badge: missing ? '!' : null, warn: true }
	]);

	const isActive = (item) => (item.match ?? [item.href]).includes(section);

	const icons = {
		book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4a2 2 0 0 0-2-2H6.5A2.5 2.5 0 0 0 4 4.5v15z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
		search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
		cart: '<circle cx="9" cy="20" r="1.6"/><circle cx="17" cy="20" r="1.6"/><path d="M3 3h2l2.4 12.2a1 1 0 0 0 1 .8h8.7a1 1 0 0 0 1-.8L20 7H6"/>',
		upload: '<path d="M12 16V4m0 0 4 4m-4-4-4 4"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/>',
		gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'
	};
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && sidebarOpen.set(false)} />

{#if $sidebarOpen}
	<div class="scrim" onclick={close} aria-hidden="true"></div>
{/if}
<aside class="sidebar" class:open={$sidebarOpen} aria-label="Primary">
	<a class="brand" href="/search" onclick={close}>
		<span class="brand-mark" aria-hidden="true">E</span>
		<span class="brand-text">
			<span class="brand-name">EJEE Importer</span>
			<span class="brand-sub">for PaperLab</span>
		</span>
	</a>

	<nav>
		{#each items as item (item.href)}
			<a
				href={item.href}
				onclick={close}
				class="nav-item"
				class:active={isActive(item)}
				aria-current={isActive(item) ? 'page' : undefined}
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					{@html icons[item.icon]}
				</svg>
				<span>{item.label}</span>
				{#if item.badge}
					<span class="nav-badge" class:warn={item.warn}>{item.badge}</span>
				{/if}
			</a>
		{/each}
	</nav>

	<div class="ledger" aria-label="Processing status">
		<div class="ledger-cell">
			<span class="ledger-num">{jobs.queued ?? 0}</span>
			<span class="ledger-label">Queued</span>
		</div>
		<div class="ledger-cell">
			<span class="ledger-num">{jobs.running ?? 0}</span>
			<span class="ledger-label">Running</span>
		</div>
		<div class="ledger-cell">
			<span class="ledger-num">{jobs.failed ?? 0}</span>
			<span class="ledger-label">Failed</span>
		</div>
		<div class="ledger-cell">
			<span class="ledger-num">{jobs.done ?? 0}</span>
			<span class="ledger-label">Published</span>
		</div>
	</div>

	<a class="setup" class:ready={s && !missing} href="/settings" onclick={close}>
		<span class="dot" aria-hidden="true"></span>
		<span>
			<span class="setup-title">{!s ? 'Connecting…' : missing ? 'Setup needed' : 'Ready to process'}</span>
			<span class="setup-sub">
				{#if !s}
					Waiting for the app
				{:else if missing}
					{missing} setting{missing === 1 ? '' : 's'} missing
				{:else if s.queue?.paused && (s.jobs?.queued ?? 0) > 0}
					Queue paused
				{:else}
					Spent {s.spent ? `$${s.spent.usd.toFixed(2)} · ₹${s.spent.inr_gst.toFixed(0)} incl. GST` : '$0'}
				{/if}
			</span>
		</span>
	</a>
</aside>

<style>
	.sidebar {
		width: 264px;
		flex-shrink: 0;
		height: 100dvh;
		position: fixed;
		top: 0;
		left: 0;
		z-index: 40;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 20px 14px;
		background: var(--pl-surface);
		border-right: 1px solid var(--pl-line);
	}
	.scrim {
		display: none;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 12px;
		text-decoration: none;
		padding: 4px 8px 14px;
	}
	.brand-mark {
		width: 40px;
		height: 40px;
		border-radius: 12px;
		display: grid;
		place-items: center;
		background: var(--pl-pine);
		color: #fff;
		font-family: var(--pl-font-display);
		font-size: 1.3rem;
	}
	[data-theme='dark'] .brand-mark {
		color: #141311;
	}
	.brand-text {
		display: flex;
		flex-direction: column;
		line-height: 1.2;
	}
	.brand-name {
		font-family: var(--pl-font-display);
		font-size: 1.25rem;
		letter-spacing: 0.02em;
	}
	.brand-sub {
		font-size: 0.8rem;
		color: var(--pl-ink-soft);
	}
	nav {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.nav-item {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 10px 12px;
		border-radius: 10px;
		text-decoration: none;
		color: var(--pl-ink-soft);
		font-weight: 500;
		border-left: 3px solid transparent;
	}
	.nav-item svg {
		width: 20px;
		height: 20px;
		flex-shrink: 0;
	}
	.nav-item:hover {
		background: var(--pl-raised);
		color: var(--pl-ink);
	}
	.nav-item.active {
		background: var(--pl-raised);
		color: var(--pl-ink);
		border-left-color: var(--pl-seal);
		font-weight: 600;
	}
	.nav-badge {
		margin-left: auto;
		background: var(--pl-pine-soft);
		color: var(--pl-pine);
		border-radius: var(--pl-radius-pill);
		padding: 1px 10px;
		font-family: var(--pl-font-mono);
		font-size: 0.75rem;
	}
	.nav-badge.warn {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.ledger {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
		margin-top: auto;
		padding-top: 12px;
	}
	.ledger-cell {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-sm);
		padding: 6px 10px;
		display: flex;
		flex-direction: column;
	}
	.ledger-num {
		font-family: var(--pl-font-mono);
		font-size: 0.95rem;
		font-weight: 600;
	}
	.ledger-label {
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--pl-ink-soft);
	}
	.setup {
		display: flex;
		align-items: center;
		gap: 12px;
		border-top: 1px solid var(--pl-line);
		padding: 14px 4px 0;
		margin-top: 8px;
		text-decoration: none;
	}
	.setup > span:last-child {
		display: flex;
		flex-direction: column;
	}
	.dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		background: var(--pl-ochre);
		flex-shrink: 0;
		margin-left: 6px;
	}
	.setup.ready .dot {
		background: var(--pl-pine);
	}
	.setup-title {
		font-weight: 600;
		font-size: 0.85rem;
	}
	.setup-sub {
		font-size: 0.78rem;
		color: var(--pl-ink-soft);
	}
	@media (max-width: 900px) {
		.sidebar {
			transform: translateX(-100%);
			transition: transform 160ms ease;
		}
		.sidebar.open {
			transform: none;
			box-shadow: var(--pl-shadow-md);
		}
		.scrim {
			display: block;
			position: fixed;
			inset: 0;
			z-index: 39;
			background: rgb(0 0 0 / 0.35);
		}
	}
</style>
