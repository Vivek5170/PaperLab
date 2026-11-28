<script>
	import { onMount } from 'svelte';
	import { api } from '$lib/api.js';
	import { appStatus, refreshStatus, toast } from '$lib/stores.js';

	let saved = $state(null); // public settings from the app (no secrets)
	let form = $state({
		server_url: '',
		ejee_db: '',
		uploads: '',
		meta_api_key: '',
		archivist_password: '',
		extra_keys: ''
	});
	let busy = $state('');
	let error = $state('');
	let tests = $state({}); // what -> {ok, text}
	let showKey = $state(false);

	const index = $derived($appStatus?.index);
	const missing = $derived($appStatus?.missing ?? []);
	const isMissing = (key) => missing.some((m) => m.key === key);

	async function load() {
		try {
			saved = await api.settings();
			form = {
				server_url: saved.server_url,
				ejee_db: saved.ejee_db,
				uploads: saved.uploads,
				extra_keys: '',
				meta_api_key: '',
				archivist_password: ''
			};
		} catch (e) {
			error = e.message;
		}
	}

	async function save(e) {
		e?.preventDefault();
		busy = 'save';
		error = '';
		try {
			const { extra_keys, ...body } = form;
			// Blank secret fields keep the saved value; "Clear" sends "".
			if (!body.meta_api_key) body.meta_api_key = null;
			if (!body.archivist_password) body.archivist_password = null;
			// Typed extra keys replace the saved list; blank keeps it.
			const lines = extra_keys.split(/\s+/).map((s) => s.trim()).filter(Boolean);
			body.extra_meta_keys = lines.length ? lines : null;
			saved = await api.saveSettings(body);
			form.meta_api_key = '';
			form.archivist_password = '';
			form.extra_keys = '';
			toast('Settings saved.', 'ok');
			await refreshStatus();
			return true;
		} catch (err) {
			error = err.message;
			return false;
		} finally {
			busy = '';
		}
	}

	async function clearSecret(key) {
		busy = 'save';
		try {
			saved = await api.saveSettings({ [key]: key === 'extra_meta_keys' ? [] : '' });
			toast('Removed.', 'ok');
			refreshStatus();
		} catch (err) {
			error = err.message;
		} finally {
			busy = '';
		}
	}

	async function test(what) {
		// Test what is typed: save first so the check uses the current values.
		if (!(await save())) return;
		busy = `test-${what}`;
		tests = { ...tests, [what]: { ok: null, text: 'Checking…' } };
		try {
			const r = await api.test(what);
			let text;
			if (!r.ok) text = r.detail;
			else if (what === 'server') text = `Connected to ${r.url}; the archivist password works.`;
			else if (what === 'meta') text = r.note ?? (r.verified ? 'The model endpoint accepted the key.' : '');
			else text = 'EJEE database and uploads found.';
			tests = { ...tests, [what]: { ok: r.ok, text } };
		} catch (err) {
			tests = { ...tests, [what]: { ok: false, text: err.message } };
		} finally {
			busy = '';
		}
	}

	async function rebuild() {
		busy = 'index';
		try {
			await api.rebuildIndex();
			toast('Rebuilding the search index in the background.', 'ok');
			refreshStatus();
		} catch (err) {
			error = err.message;
		} finally {
			busy = '';
		}
	}

	onMount(load);
</script>

<svelte:head><title>Settings - EJEE Importer</title></svelte:head>

<h1>Settings</h1>
<p class="pl-sub intro">
	Stored only on this computer, in the app's private data folder (outside Git). The key and password are never sent to
	the browser again or written to logs.
	{#if missing.length}<strong>Processing stays locked until every field marked “Required” is set.</strong>{/if}
</p>

{#if error}
	<div class="pl-error" role="alert">{error}</div>
{/if}

{#if saved}
	<form onsubmit={save} class="sections">
		<section class="pl-card" aria-labelledby="sec-server">
			<div class="sec-head">
				<h2 id="sec-server">PaperLab server</h2>
				<span class="tag" class:req={isMissing('server_url') || isMissing('archivist_password')}>
					{isMissing('server_url') || isMissing('archivist_password') ? 'Required' : 'Set'}
				</span>
			</div>
			<p class="pl-hint">Finished parts are published here through PaperLab's archivist bundle upload.</p>
			<label class="pl-field">
				Server link
				<input type="url" bind:value={form.server_url} placeholder="https://paperlab.example.org" autocomplete="url" spellcheck="false" />
				<span class="pl-hint">HTTPS for a remote server; http://127.0.0.1:8000 works for a PaperLab on this computer.</span>
			</label>
			<label class="pl-field">
				Archivist password
				<input type="password" bind:value={form.archivist_password} autocomplete="current-password"
					placeholder={saved.archivist_password_set ? `Saved (${saved.archivist_password_hint}) · type to replace` : 'PaperLab archivist password'} />
			</label>
			<div class="row">
				<button type="button" class="pl-btn" disabled={!!busy} onclick={() => test('server')}>
					{busy === 'test-server' ? 'Testing…' : 'Save & test connection'}
				</button>
				{#if saved.archivist_password_set}
					<button type="button" class="link" disabled={!!busy} onclick={() => clearSecret('archivist_password')}>Forget password</button>
				{/if}
			</div>
			{#if tests.server}<p class="result" class:ok={tests.server.ok} class:bad={tests.server.ok === false}>{tests.server.text}</p>{/if}
		</section>

		<section class="pl-card" aria-labelledby="sec-meta">
			<div class="sec-head">
				<h2 id="sec-meta">Meta API (Muse)</h2>
				<span class="tag" class:req={isMissing('meta_api_key')}>{isMissing('meta_api_key') ? 'Required' : 'Set'}</span>
			</div>
			<p class="pl-hint">Used only for transcription and topic tagging. Search, review and repairs never use it.</p>
			<label class="pl-field">
				Meta API key
				<span class="keyrow">
					<input type={showKey ? 'text' : 'password'} bind:value={form.meta_api_key} autocomplete="off" spellcheck="false"
						placeholder={saved.meta_api_key_set ? `Saved (${saved.meta_api_key_hint}) · type to replace` : 'Paste your key'} />
					<button type="button" class="pl-btn" onclick={() => (showKey = !showKey)} aria-pressed={showKey}>{showKey ? 'Hide' : 'Show'}</button>
				</span>
			</label>
			<label class="pl-field">
				Extra keys for parallel processing
				<textarea rows="2" bind:value={form.extra_keys} autocomplete="off" spellcheck="false"
					placeholder={saved.extra_meta_keys_count
						? `${saved.extra_meta_keys_count} saved (${saved.extra_meta_keys_hints.join(', ')}) · type to replace all`
						: 'Optional: one key per line, ideally from different accounts'}></textarea>
				<span class="pl-hint">
					Each key runs its own worker on the same queue, so 3 keys ≈ 3× faster. A rejected or rate-limited key
					is set aside and the others continue.
				</span>
			</label>
			<div class="row">
				<button type="button" class="pl-btn" disabled={!!busy} onclick={() => test('meta')}>
					{busy === 'test-meta' ? 'Testing…' : 'Save & test keys'}
				</button>
				{#if saved.extra_meta_keys_count}
					<button type="button" class="link" disabled={!!busy} onclick={() => clearSecret('extra_meta_keys')}>Forget extra keys</button>
				{/if}
				{#if saved.meta_api_key_set}
					<button type="button" class="link" disabled={!!busy} onclick={() => clearSecret('meta_api_key')}>Forget key</button>
				{/if}
			</div>
			{#if tests.meta}<p class="result" class:ok={tests.meta.ok} class:bad={tests.meta.ok === false}>{tests.meta.text}</p>{/if}
		</section>

		<section class="pl-card" aria-labelledby="sec-src">
			<div class="sec-head">
				<h2 id="sec-src">EJEE source</h2>
				<span class="tag" class:req={isMissing('ejee_db') || isMissing('uploads')}>
					{isMissing('ejee_db') || isMissing('uploads') ? 'Required' : 'Set'}
				</span>
			</div>
			<p class="pl-hint">Read-only: the app never writes to the EJEE database or its uploads.</p>
			<label class="pl-field">
				EJEE database file
				<input bind:value={form.ejee_db} placeholder="/path/to/ejee.db" spellcheck="false" />
			</label>
			<label class="pl-field">
				Uploads folder
				<input bind:value={form.uploads} placeholder="/path/to/uploads" spellcheck="false" />
			</label>
			<div class="index">
				{#if index?.building}
					<p><strong>Building search index…</strong> {index.progress} / {index.total || '…'} sources</p>
					<progress max={index.total || 1} value={index.progress}></progress>
				{:else if index?.built}
					<p>
						Search index: {index.items?.toLocaleString()} questions from {index.sources} sources · built {index.built_at}
						{#if index.stale}<strong class="warn"> · out of date (EJEE changed)</strong>{/if}
					</p>
					{#if index.unconvertible}
						<p class="pl-hint">
							{index.unconvertible} EJEE item{index.unconvertible === 1 ? '' : 's'} cannot be converted by anyone (image file
							missing, no body box, or a solution without its question) and {index.unconvertible === 1 ? 'is' : 'are'} not listed.
						</p>
					{/if}
				{:else if index?.error}
					<p class="warn">Index build failed: {index.error}</p>
				{:else}
					<p class="pl-sub">No search index yet. Saving valid paths builds it (a few minutes, once).</p>
				{/if}
				<button type="button" class="pl-btn" disabled={!!busy || index?.building || isMissing('ejee_db') || isMissing('uploads')} onclick={rebuild}>
					Rebuild index
				</button>
			</div>
		</section>

		<div class="savebar">
			<button type="submit" class="pl-btn pl-btn-primary" disabled={!!busy}>{busy === 'save' ? 'Saving…' : 'Save settings'}</button>
			{#if !missing.length}<span class="pl-sub">All set. <a href="/process">Go to Process & Publish</a></span>{/if}
		</div>
	</form>
{:else if !error}
	<p class="pl-sub">Loading…</p>
{/if}

<style>
	h1 {
		font-size: 2rem;
		margin-bottom: 4px;
	}
	.intro {
		margin-top: 0;
		max-width: 760px;
	}
	.sections {
		display: flex;
		flex-direction: column;
		gap: 16px;
		margin-top: 16px;
		max-width: 760px;
	}
	section {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.sec-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 12px;
	}
	h2 {
		font-size: 1.2rem;
	}
	.tag {
		border-radius: var(--pl-radius-pill);
		padding: 2px 10px;
		font-size: 0.75rem;
		font-weight: 600;
		background: var(--pl-pine-soft);
		color: var(--pl-pine);
	}
	.tag.req {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.keyrow {
		display: flex;
		gap: 8px;
	}
	.keyrow input {
		flex: 1;
		min-width: 0;
	}
	.row {
		display: flex;
		gap: 12px;
		align-items: center;
		flex-wrap: wrap;
	}
	.link {
		border: none;
		background: none;
		color: var(--pl-seal);
		font-weight: 600;
		font-size: 0.85rem;
		padding: 0 4px;
	}
	.result {
		margin: 0;
		font-size: 0.85rem;
		padding: 8px 12px;
		border-radius: var(--pl-radius-sm);
		background: var(--pl-raised);
	}
	.result.ok {
		background: var(--pl-pine-soft);
		color: var(--pl-pine);
	}
	.result.bad {
		background: var(--pl-ochre-soft);
		color: var(--pl-ochre);
	}
	.index {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 8px;
		font-size: 0.85rem;
	}
	.index p {
		margin: 0;
	}
	progress {
		width: 100%;
		accent-color: var(--pl-pine);
	}
	.warn {
		color: var(--pl-ochre);
	}
	.savebar {
		display: flex;
		align-items: center;
		gap: 16px;
		flex-wrap: wrap;
		position: sticky;
		bottom: 0;
		padding: 12px 0;
		background: var(--pl-paper);
		border-top: 1px solid var(--pl-line);
	}
</style>
