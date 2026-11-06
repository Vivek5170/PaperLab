/**
 * Builder draft store: independent builder state in localStorage
 * (`pl-build-v1`). Drafts hold deep-cloned blocks with stable ids —
 * cart edits/deletes can never leak in. Same hardened pattern as
 * carts.js: schema validate + repair, corrupt backup, quota-safe,
 * cross-tab sync. Never throws.
 */
import { browser } from '$app/environment';
import { writable, derived } from 'svelte/store';
import {
	BUILDER_SCHEMA_VERSION,
	createDraft,
	importBlocks,
	autoGroup,
	addSection,
	renameSection,
	deleteSection,
	setSectionAtype,
	moveSection,
	moveBlock,
	moveBlockToSection,
	removeBlock,
	restoreBlock,
	setKeyOverride,
	validateDraft
} from './builderModel.js';
import { assignNumbers, flattenDraft } from './numbering.js';

export const BUILDER_KEY = 'pl-build-v1';

function loadInitial() {
	const blank = createDraft('paper');
	if (!browser) return { draft: blank, corrupt: false };
	try {
		const raw = localStorage.getItem(BUILDER_KEY);
		if (!raw) return { draft: blank, corrupt: false };
		const { ok, draft } = validateDraft(JSON.parse(raw));
		return { draft, corrupt: !ok };
	} catch {
		return { draft: blank, corrupt: true };
	}
}

const initial = loadInitial();

export const builderCorrupt = writable(initial.corrupt);

function persist(draft) {
	if (!browser) return;
	try {
		localStorage.setItem(BUILDER_KEY, JSON.stringify(draft));
	} catch {
		/* quota/private mode: keep in-memory copy, stay functional */
	}
}

persist(initial.draft);
if (browser && initial.corrupt) {
	try {
		localStorage.setItem(
			`${BUILDER_KEY}-corrupt-${Date.now()}`,
			localStorage.getItem(BUILDER_KEY) ?? ''
		);
	} catch { /* best-effort backup */ }
}

export const builderStore = writable(initial.draft);

if (browser) {
	builderStore.subscribe((d) => persist(d));
	try {
		window.addEventListener('storage', (e) => {
			if (e.key !== BUILDER_KEY || !e.newValue) return;
			try {
				const { ok, draft } = validateDraft(JSON.parse(e.newValue));
				if (ok) builderStore.set(draft);
			} catch { /* ignore cross-tab garbage */ }
		});
	} catch { /* no window */ }
}

/** Blocks flattened in actual document order — the ONE numbering input. */
export const docOrder = derived(builderStore, ($d) => flattenDraft($d));

/** The ONE numbering result. Blocks, Key and Solutions all consume this. */
export const numbering = derived(docOrder, ($o) => assignNumbers($o));

export const blockTotal = derived(builderStore, ($d) => Object.keys($d.blocks ?? {}).length);

/**
 * Filed answer keys parsed from solution tex, per block in sub order:
 * {blockId: [key0, key1...]}. Session-only (never persisted): re-parsed
 * from the same cached fetch the solutions use. Manual overrides in
 * draft.keyOverride always win over these.
 */
export const parsedKeys = writable({});

export const builder = {
	setTitle(title) {
		builderStore.update((d) => ({
			...d, title: String(title ?? '').slice(0, 120), updatedAt: new Date().toISOString()
		}));
	},
	newDraft(mode) {
		builderStore.set(createDraft(mode === 'assignment' ? 'assignment' : 'paper'));
	},
	importFromCart(items, opts) {
		let out = { added: [], skipped: [] };
		builderStore.update((d) => {
			const r = importBlocks(d, items, opts);
			out = { added: r.added, skipped: r.skipped };
			return r.draft;
		});
		return out;
	},
	autoGroup() {
		let grouped = false;
		builderStore.update((d) => {
			const r = autoGroup(d);
			grouped = r.grouped;
			return r.draft;
		});
		return grouped;
	},
	addSection(input) {
		let id = null;
		builderStore.update((d) => {
			const r = addSection(d, input);
			id = r.id;
			return r.draft;
		});
		return id;
	},
	renameSection(id, title) {
		let ok = false;
		builderStore.update((d) => {
			const r = renameSection(d, id, title);
			ok = r.renamed;
			return r.draft;
		});
		return ok;
	},
	deleteSection(id) {
		let r0 = { deleted: false };
		builderStore.update((d) => {
			const r = deleteSection(d, id);
			r0 = r;
			return r.draft;
		});
		return r0;
	},
	setSectionAtype(id, atype) {
		let r0 = { changed: false };
		builderStore.update((d) => {
			const r = setSectionAtype(d, id, atype);
			r0 = r;
			return r.draft;
		});
		return r0;
	},
	moveSection(from, to) {
		let moved = false;
		builderStore.update((d) => {
			const r = moveSection(d, from, to);
			moved = r.moved;
			return r.draft;
		});
		return moved;
	},
	moveBlock(id, dir) {
		let moved = false;
		builderStore.update((d) => {
			const r = moveBlock(d, id, dir);
			moved = r.moved;
			return r.draft;
		});
		return moved;
	},
	moveBlockToSection(id, targetId) {
		let r0 = { moved: false };
		builderStore.update((d) => {
			const r = moveBlockToSection(d, id, targetId);
			r0 = r;
			return r.draft;
		});
		return r0;
	},
	removeBlock(id) {
		let snapshot = null;
		builderStore.update((d) => {
			const r = removeBlock(d, id);
			snapshot = r.snapshot ?? null;
			return r.draft;
		});
		return snapshot;
	},
	restoreBlock(snapshot, fallbackSectionId = null) {
		let restored = false;
		builderStore.update((d) => {
			let r = restoreBlock(d, snapshot);
			if (!r.restored && r.reason === 'section-gone' && fallbackSectionId) {
				r = restoreBlock(d, { ...snapshot, sectionId: fallbackSectionId });
			}
			restored = r.restored;
			return r.draft;
		});
		return restored;
	},
	setOverride(blockId, subIndex, text) {
		builderStore.update((d) => setKeyOverride(d, blockId, subIndex, text));
	},
	setParsedKeys(blockId, keys) {
		parsedKeys.update((m) => ({ ...m, [blockId]: keys }));
	}
};
