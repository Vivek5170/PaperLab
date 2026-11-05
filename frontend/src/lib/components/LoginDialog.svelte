<script>
	import { api } from '$lib/api.js';
	import { loginOpen, role } from '$lib/stores.js';

	let password = $state('');
	let error = $state('');
	let busy = $state(false);
	let dialog = $state(null);

	$effect(() => {
		if ($loginOpen) {
			password = '';
			error = '';
			if (dialog && !dialog.open) dialog.showModal();
		} else if (dialog?.open) {
			dialog.close();
		}
	});

	async function submit(event) {
		event.preventDefault();
		busy = true;
		error = '';
		try {
			await api.login(password);
			role.set('archivist');
			loginOpen.set(false);
		} catch {
			error = 'Wrong password. Try again.';
		} finally {
			busy = false;
		}
	}
</script>

<dialog
	bind:this={dialog}
	aria-label="Archivist login"
	class="login"
	onclose={() => loginOpen.set(false)}
>
	<form method="dialog" onsubmit={submit}>
		<h2>Archivist login</h2>
		<p class="pl-sub">Unlocks the workshop: tagging, syllabus, intake, ledger.</p>
		<label>
			Password
			<input
				type="password"
				autocomplete="current-password"
				bind:value={password}
				aria-describedby={error ? 'login-error' : undefined}
			/>
		</label>
		{#if error}
			<p class="pl-error" id="login-error" role="alert">{error}</p>
		{/if}
		<div class="row">
			<button type="submit" class="pl-btn pl-btn-primary" disabled={busy}>
				{busy ? 'Checking…' : 'Unlock'}
			</button>
			<button type="button" class="pl-btn" onclick={() => loginOpen.set(false)}>
				Cancel
			</button>
		</div>
	</form>
</dialog>

<style>
	.login {
		border: 1px solid var(--pl-line);
		border-radius: var(--pl-radius-lg);
		background: var(--pl-surface);
		color: var(--pl-ink);
		padding: 24px;
		max-width: 380px;
		width: calc(100vw - 48px);
	}
	.login::backdrop {
		background: rgb(0 0 0 / 0.4);
	}
	.login h2 {
		font-size: 1.3rem;
		margin-bottom: 4px;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-weight: 600;
		font-size: 0.85rem;
		margin-top: 12px;
	}
	.row {
		display: flex;
		gap: 8px;
		margin-top: 16px;
	}
</style>
