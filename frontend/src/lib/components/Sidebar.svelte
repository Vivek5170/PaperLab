<script>
	import { page } from '$app/stores';
	import { role, loginOpen, sidebarOpen } from '$lib/stores.js';
	import { api } from '$lib/api.js';

	let props = $props();

	function close() {
		sidebarOpen.set(false);
	}

	async function toggleView() {
		if ($role === 'archivist') {
			await api.logout().catch(() => {});
			role.set('student');
		} else {
			loginOpen.set(true);
		}
	}

	const section = $derived('/' + ($page.url.pathname.split('/')[1] || 'archive'));
	const isArchivist = $derived($role === 'archivist');

	const items = $derived([
		{ href: '/archive', label: 'Archive', icon: 'book' },
		{ href: '/search', label: 'Search Questions', icon: 'search' },
		{ href: '/cart', label: 'Cart', icon: 'cart' },
		{ href: '/builder', label: 'Paper Builder', icon: 'builder' },
		{ href: '/inbox', label: 'Tagging Inbox', badge: props.inboxCount, admin: true, icon: 'tag' },
		{ href: '/syllabus', label: 'Syllabus Map', admin: true, icon: 'map' },
		{ href: '/intake', label: 'Intake & Pipeline', admin: true, icon: 'upload' },
		{ href: '/ledger', label: 'Usage Ledger', admin: true, icon: 'ledger' }
	]);

	const icons = {
		book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4a2 2 0 0 0-2-2H6.5A2.5 2.5 0 0 0 4 4.5v15z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
		search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
		cart: '<circle cx="9" cy="20" r="1.6"/><circle cx="17" cy="20" r="1.6"/><path d="M3 3h2l2.4 12.2a1 1 0 0 0 1 .8h8.7a1 1 0 0 0 1-.8L20 7H6"/>',
		tag: '<path d="M12 2H2v10l9.3 9.3a1 1 0 0 0 1.4 0l8.6-8.6a1 1 0 0 0 0-1.4L12 2z"/><circle cx="7" cy="7" r="1.5"/>',
		map: '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/>',
		upload:
			'<path d="M12 16V4m0 0 4 4m-4-4-4 4"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/>',
		ledger: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 10h8M8 14h8M8 18h5"/>',
		builder: '<rect x="4" y="3" width="12" height="16" rx="2"/><path d="M8 7h5M8 11h5M8 15h3"/><path d="M16 17h4a1 1 0 0 0 1-1v-3"/>'
	};
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && sidebarOpen.set(false)} />

{#if $sidebarOpen}
	<div class="scrim" onclick={close} aria-hidden="true"></div>
{/if}
<aside class="sidebar" class:open={$sidebarOpen} aria-label="Primary">
	<a class="brand" href="/archive" onclick={close}>
		<span class="brand-mark" aria-hidden="true">P</span>
		<span class="brand-text">
			<span class="brand-name">PaperLab</span>
			<span class="brand-sub">Physics</span>
		</span>
	</a>

	<nav>
		{#each items.filter((i) => !i.admin || isArchivist) as item (item.href)}
			<a
				href={item.href}
				onclick={close}
				class="nav-item"
				class:active={section === item.href}
				aria-current={section === item.href ? 'page' : undefined}
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					{@html icons[item.icon]}
				</svg>
				<span>{item.label}</span>
				{#if item.badge}
					<span class="nav-badge">{item.badge}</span>
				{/if}
			</a>
		{/each}
		{#if !isArchivist}
			<p class="locked-note">Workshop pages unlock after archivist login.</p>
		{/if}
	</nav>

	<div class="ledger" aria-label="Pipeline status">
		<div class="ledger-cell">
			<span class="ledger-num">{props.counts.done}</span>
			<span class="ledger-label">Done</span>
		</div>
		<div class="ledger-cell">
			<span class="ledger-num">{props.counts.queued}</span>
			<span class="ledger-label">Queued</span>
		</div>
		<div class="ledger-cell">
			<span class="ledger-num">{props.counts.running}</span>
			<span class="ledger-label">Running</span>
		</div>
		<div class="ledger-cell">
			<span class="ledger-num">{props.counts.failed}</span>
			<span class="ledger-label">Failed</span>
		</div>
	</div>

	<div class="role-switch">
		<button
			type="button"
			role="switch"
			aria-checked={isArchivist}
			aria-label="Archivist view: editing tools"
			class="switch"
			class:on={isArchivist}
			onclick={toggleView}
		>
			<span class="knob"></span>
		</button>
		<div>
			<div class="role-title">{isArchivist ? 'Archivist view' : 'Student view'}</div>
			<div class="role-sub">
				{isArchivist ? 'Editing tools are visible' : 'Editing tools are hidden'}
			</div>
		</div>
	</div>
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
		background: var(--pl-seal);
		color: #fff;
		font-family: var(--pl-font-display);
		font-size: 1.3rem;
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
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
		border-radius: var(--pl-radius-pill);
		padding: 1px 10px;
		font-family: var(--pl-font-mono);
		font-size: 0.75rem;
	}
	.locked-note {
		font-size: 0.8rem;
		color: var(--pl-ink-soft);
		border: 1px dashed var(--pl-line);
		border-radius: var(--pl-radius-sm);
		padding: 8px 10px;
		margin: 6px 0 0;
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
	.role-switch {
		display: flex;
		align-items: center;
		gap: 12px;
		border-top: 1px solid var(--pl-line);
		padding-top: 14px;
		margin-top: 8px;
	}
	.switch {
		width: 48px;
		height: 28px;
		min-height: 28px;
		border-radius: var(--pl-radius-pill);
		border: 1px solid var(--pl-line);
		background: var(--pl-raised);
		position: relative;
		padding: 0;
		flex-shrink: 0;
	}
	.knob {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--pl-ink-soft);
		transition: left 160ms ease;
	}
	.switch.on .knob {
		left: 22px;
		background: var(--pl-seal);
	}
	.role-title {
		font-weight: 600;
		font-size: 0.85rem;
	}
	.role-sub {
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
