/**
 * Builder draft model (pure, no localStorage, no Svelte). builder.js wraps
 * these with persistence. node --test covers them.
 *
 * Identity rules (stable draft identity):
 * - Block ids are minted ONLY at import (fresh crypto ids). Ordinary
 *   edits, reordering and reloads never regenerate them.
 * - Key overrides are keyed `blockId:subIndex` — never generated numbers —
 *   so renumbering after reorder/delete keeps answers glued to questions.
 * - Import deep-clones cart items; the draft never references cart objects,
 *   so cart edits/deletes can never mutate builder state.
 * - Reimport detects identity dupes (paperId+number already present) and
 *   skips them unless allowDupes is explicitly confirmed.
 *
 * Sections group by RAW question type: scq, par-scq, msq, par-msq,
 * int, num, mtx, ... each get their own section (A, B, C...). par-* is
 * never merged into its base type. Passage blocks stay atomic — never
 * split — but group strictly by their own type code.
 */


export const BUILDER_SCHEMA_VERSION = 1;
/** Raw question types; paper sections follow this order. par-* codes
 * are distinct sections, never merged into their base type. */
export const SECTION_TYPES = ['scq', 'msq', 'int', 'num', 'mtx',
  'par-scq', 'par-msq', 'par-int', 'par-num', 'par-mtx', 'par-mix', 'unknown'];

export function newBlockId() {
	try {
		if (typeof crypto !== 'undefined' && crypto.randomUUID) return `b-${crypto.randomUUID()}`;
	} catch { /* fall through */ }
	return `b-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e9).toString(36)}`;
}

export function newSectionId() {
	return `s-${newBlockId().slice(2)}`;
}

function now() {
	return new Date().toISOString();
}

const isPid = (v) => typeof v === 'number' && Number.isFinite(v);

export function createDraft(mode = 'paper', title = '') {
	const t = now();
	if (mode === 'assignment') {
		return {
			version: BUILDER_SCHEMA_VERSION, mode, title: String(title ?? ''),
			sections: [{ id: newSectionId(), title: 'Assignment', atype: 'mixed', locked: true, blockIds: [] }],
			blocks: {}, keyOverride: {}, createdAt: t, updatedAt: t
		};
	}
	return {
		version: BUILDER_SCHEMA_VERSION, mode: 'paper', title: String(title ?? ''),
		sections: [], blocks: {}, keyOverride: {}, createdAt: t, updatedAt: t
	};
}

/** Normalize one cart/draft item into a block identity snapshot. Null when invalid. */
export function toBlock(src) {
	if (!src || typeof src !== 'object') return null;
	const paperId = typeof src.paperId === 'string' ? parseInt(src.paperId, 10) : src.paperId;
	const number = src.number != null ? String(src.number) : '';
	if (!isPid(paperId) || !number) return null;
	return {
		id: newBlockId(),
		paperId,
		number,
		qtype: typeof src.qtype === 'string' && src.qtype ? src.qtype.slice(0, 20) : 'unknown'
	};
}

export const blockKey = (paperId, number) => `${paperId}::${String(number)}`;

function identitySet(draft) {
	return new Set(Object.values(draft.blocks ?? {}).map((b) => blockKey(b.paperId, b.number)));
}

function touch(draft) {
	return { ...draft, updatedAt: now() };
}

/**
 * Import items as fresh blocks. Dupes (identity already in draft) are
 * skipped unless allowDupes. Paper drafts regroup automatically on every
 * import — sections are derived (A, B, C…), never managed by hand.
 * Assignment appends to its single flat list.
 * Returns {draft, added:[blockIds], skipped:[{paperId,number}]}.
 */
export function importBlocks(draft, items, { allowDupes = false } = {}) {
	const seen = identitySet(draft);
	const blocks = { ...(draft?.blocks ?? {}) };
	const added = [];
	const skipped = [];
	for (const src of items ?? []) {
		const b = toBlock(src);
		if (!b) continue;
		const k = blockKey(b.paperId, b.number);
		if (seen.has(k) && !allowDupes) {
			skipped.push({ paperId: b.paperId, number: b.number });
			continue;
		}
		seen.add(k);
		blocks[b.id] = b;
		added.push(b.id);
	}
	if ((draft?.mode ?? 'paper') === 'assignment') {
		const base = draft?.sections?.length > 0 ? draft : createDraft('assignment', draft?.title ?? '');
		const sections = base.sections.map((s) => ({ ...s, blockIds: [...s.blockIds] }));
		sections[0].blockIds.push(...added);
		return { draft: touch({ ...base, blocks, sections }), added, skipped };
	}
	return { ...autoGroup({ ...draft, blocks }), added, skipped };
}

/**
 * Section gate. Locked (assignment) sections accept everything. Passage
 * sections accept paragraph blocks of ANY qtype and refuse singles;
 * typed sections accept their normalized type (par-scq == scq).
 */
export function sectionAccepts(section, block) {
	if (!section || !block) return false;
	if (section.locked) return true;
	return (block.qtype || 'unknown') === section.atype;
}

/**
 * Rebuild paper sections deterministically: one section per RAW question
 * type, in SECTION_TYPES order. par-scq is its own section, distinct from
 * SCQ; no paragraph exception exists. Order inside each bucket follows
 * current document order; brand-new blocks (no position yet) append at
 * the end in arrival order.
 */
export function autoGroup(draft) {
	if (draft.mode !== 'paper') return { draft, grouped: false };
	const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
	const buckets = new Map();
	for (const b of Object.values(draft.blocks ?? {})) {
		const t = (b.qtype || 'unknown').slice(0, 20);
		if (!buckets.has(t)) buckets.set(t, []);
		buckets.get(t).push(b.id);
	}
	// Preserve current document order inside each bucket.
	const docOrder = [];
	for (const s of draft.sections) for (const bid of s.blockIds) docOrder.push(bid);
	const pos = new Map(docOrder.map((id, i) => [id, i]));
	const byPos = (a, b) => (pos.get(a) ?? Number.MAX_SAFE_INTEGER) - (pos.get(b) ?? Number.MAX_SAFE_INTEGER);
	const sections = [];
	let li = 0;
	for (const t of SECTION_TYPES) {
		if (!buckets.has(t)) continue;
		sections.push({
			id: newSectionId(),
			title: `Section ${letters[li++] ?? `X${li}`} · ${t.toUpperCase()}`,
			atype: t,
			blockIds: buckets.get(t).slice().sort(byPos)
		});
	}
	return { draft: touch({ ...draft, sections }), grouped: true };
}

export function addSection(draft, { title, atype }) {
	const t = SECTION_TYPES.includes(atype) ? atype : 'unknown';
	const clean = String(title ?? '').trim().slice(0, 80) || `Section ${draft.sections.length + 1}`;
	const s = { id: newSectionId(), title: clean, atype: t, blockIds: [] };
	return { draft: touch({ ...draft, sections: [...draft.sections, s] }), id: s.id };
}

export function renameSection(draft, sectionId, title) {
	const clean = String(title ?? '').trim().slice(0, 80);
	if (!clean) return { draft, renamed: false };
	return {
		draft: touch({
			...draft,
			sections: draft.sections.map((s) => (s.id === sectionId ? { ...s, title: clean } : s))
		}),
		renamed: true
	};
}

/** Delete an EMPTY paper section. Non-empty refuses (move blocks out first). */
export function deleteSection(draft, sectionId) {
	const s = draft.sections.find((x) => x.id === sectionId);
	if (!s || s.locked) return { draft, deleted: false, reason: 'locked' };
	if (s.blockIds.length > 0) return { draft, deleted: false, reason: 'non-empty' };
	return {
		draft: touch({ ...draft, sections: draft.sections.filter((x) => x.id !== sectionId) }),
		deleted: true
	};
}

/** Retype an EMPTY section only — never silently invalidate placed blocks. */
export function setSectionAtype(draft, sectionId, atype) {
	const s = draft.sections.find((x) => x.id === sectionId);
	if (!s || s.locked || !SECTION_TYPES.includes(atype)) return { draft, changed: false };
	if (s.blockIds.length > 0) return { draft, changed: false, reason: 'non-empty' };
	return {
		draft: touch({
			...draft,
			sections: draft.sections.map((x) => (x.id === sectionId ? { ...x, atype } : x))
		}),
		changed: true
	};
}

function locate(draft, blockId) {
	for (let i = 0; i < draft.sections.length; i++) {
		const j = draft.sections[i].blockIds.indexOf(blockId);
		if (j !== -1) return { si: i, bi: j };
	}
	return null;
}

export function moveSection(draft, from, to) {
	const n = draft.sections.length;
	if (n < 2) return { draft, moved: false };
	const f = Math.max(0, Math.min(n - 1, from | 0));
	const t = Math.max(0, Math.min(n - 1, to | 0));
	if (f === t) return { draft, moved: false };
	const sections = draft.sections.slice();
	const [s] = sections.splice(f, 1);
	sections.splice(t, 0, s);
	return { draft: touch({ ...draft, sections }), moved: true };
}

/** Step a block up/down inside its own section (atomic — whole block moves). */
export function moveBlock(draft, blockId, dir) {
	const at = locate(draft, blockId);
	if (!at) return { draft, moved: false };
	const ids = draft.sections[at.si].blockIds;
	const t = at.bi + (dir < 0 ? -1 : 1);
	if (t < 0 || t >= ids.length) return { draft, moved: false };
	const sections = draft.sections.map((s) => ({ ...s, blockIds: [...s.blockIds] }));
	const row = sections[at.si].blockIds;
	[row[at.bi], row[t]] = [row[t], row[at.bi]];
	return { draft: touch({ ...draft, sections }), moved: true };
}

/** Move a block into another section; rejects normalized-type mismatches. */
export function moveBlockToSection(draft, blockId, targetId) {
	const at = locate(draft, blockId);
	const target = draft.sections.find((s) => s.id === targetId);
	const block = draft.blocks?.[blockId];
	if (!at || !target || !block) return { draft, moved: false, reason: 'not-found' };
	if (target.id === draft.sections[at.si].id) return { draft, moved: true };
	if (!sectionAccepts(target, block)) return { draft, moved: false, reason: 'type-mismatch' };
	const sections = draft.sections.map((s) => ({ ...s, blockIds: [...s.blockIds] }));
	sections[at.si].blockIds.splice(at.bi, 1);
	sections.find((s) => s.id === targetId).blockIds.push(blockId);
	// Keep sections derived: prune a paper section left empty by the move.
	const pruned = draft.mode === 'paper'
		? sections.filter((s) => s.locked || s.blockIds.length > 0)
		: sections;
	return { draft: touch({ ...draft, sections: pruned }), moved: true };
}

/** Remove a block: section refs AND its key overrides go with it. */
export function removeBlock(draft, blockId) {
	if (!draft.blocks?.[blockId]) return { draft, removed: false };
	const snapshot = {
		block: { ...draft.blocks[blockId] },
		sectionId: (draft.sections.find((s) => s.blockIds.includes(blockId)) ?? {}).id ?? null,
		index: Math.max(0, (draft.sections.find((s) => s.blockIds.includes(blockId)) ?? { blockIds: [] }).blockIds.indexOf(blockId)),
		overrides: Object.fromEntries(
			Object.entries(draft.keyOverride ?? {}).filter(([k]) => k.startsWith(`${blockId}:`))
		)
	};
	const blocks = { ...draft.blocks };
	delete blocks[blockId];
	const keyOverride = Object.fromEntries(
		Object.entries(draft.keyOverride ?? {}).filter(([k]) => !k.startsWith(`${blockId}:`))
	);
	// Sections are fully derived: drop paper sections left empty (the
	// locked assignment list always stays).
	let sections = draft.sections.map((s) => ({
		...s, blockIds: s.blockIds.filter((id) => id !== blockId)
	}));
	if (draft.mode === 'paper') sections = sections.filter((s) => s.locked || s.blockIds.length > 0);
	return { draft: touch({ ...draft, blocks, sections, keyOverride }), removed: true, snapshot };
}

/**
 * Undo a removeBlock: reinsert the SAME block id at its old position with
 * its overrides. Fails safely when the section is gone (caller picks a
 * fallback) or the id was reused meanwhile.
 */
export function restoreBlock(draft, snapshot) {
	if (!snapshot || !snapshot.block || !snapshot.block.id) return { draft, restored: false };
	const { block, sectionId, index, overrides } = snapshot;
	if (draft.blocks?.[block.id]) return { draft, restored: false, reason: 'id-reused' };
	const si = draft.sections.findIndex((s) => s.id === sectionId);
	if (si === -1) return { draft, restored: false, reason: 'section-gone' };
	const blocks = { ...draft.blocks, [block.id]: { ...block } };
	const sections = draft.sections.map((s, i) => {
		if (i !== si) return s;
		const ids = [...s.blockIds];
		ids.splice(Math.max(0, Math.min(ids.length, index | 0)), 0, block.id);
		return { ...s, blockIds: ids };
	});
	const keyOverride = { ...(draft.keyOverride ?? {}), ...Object.fromEntries(
		Object.entries(overrides ?? {}).filter(([k, v]) => k.startsWith(`${block.id}:`) && typeof v === 'string')
	) };
	return { draft: touch({ ...draft, blocks, sections, keyOverride }), restored: true };
}

export function setKeyOverride(draft, blockId, subIndex, text) {
	const key = `${blockId}:${subIndex | 0}`;
	const clean = String(text ?? '').slice(0, 200);
	const keyOverride = { ...(draft.keyOverride ?? {}) };
	if (clean.trim()) keyOverride[key] = clean;
	else delete keyOverride[key];
	return touch({ ...draft, keyOverride });
}

/** Validate + repair a persisted draft. Never throws. */
export function validateDraft(raw) {
	const fresh = () => createDraft('paper');
	if (!raw || typeof raw !== 'object') return { ok: false, draft: fresh() };
	const mode = raw.mode === 'assignment' ? 'assignment' : 'paper';
	const blocks = {};
	for (const [id, b] of Object.entries(raw.blocks ?? {})) {
		if (typeof id !== 'string' || !id || !b || typeof b !== 'object') continue;
		const nb = toBlockKeepId(id, b);
		if (nb) blocks[id] = nb;
	}
	const seen = new Set();
	let sections = [];
	for (const s of Array.isArray(raw.sections) ? raw.sections : []) {
		if (!s || typeof s !== 'object') continue;
		const ids = [];
		for (const bid of Array.isArray(s.blockIds) ? s.blockIds : []) {
			if (blocks[bid] && !seen.has(bid)) {
				seen.add(bid);
				ids.push(bid);
			}
		}
		sections.push({
			id: typeof s.id === 'string' && s.id ? s.id : newSectionId(),
			title: String(s.title ?? 'Section').slice(0, 80) || 'Section',
			atype: SECTION_TYPES.includes(s.atype) ? s.atype : 'unknown',
			locked: !!s.locked,
			blockIds: ids
		});
	}
	if (mode === 'assignment') {
		// Exactly one locked section; every placed block survives (doc order,
		// deduped) plus orphans reattach. Never drop blocks from sections[1..].
		const all = sections.flatMap((s) => s.blockIds);
		const seen = new Set();
		const merged = [];
		for (const id of [...all, ...Object.keys(blocks).filter((id) => !all.includes(id))]) {
			if (!blocks[id] || seen.has(id)) continue;
			seen.add(id);
			merged.push(id);
		}
		const first = sections.find((s) => s.locked) ?? sections[0];
		const kept = {
			id: first?.id ?? newSectionId(),
			title: 'Assignment', atype: 'mixed', locked: true,
			blockIds: merged
		};
		const keyOverride = pruneOverrides(raw.keyOverride, blocks);
		return { ok: true, draft: { version: BUILDER_SCHEMA_VERSION, mode, title: String(raw.title ?? ''), sections: [kept], blocks, keyOverride, createdAt: raw.createdAt ?? now(), updatedAt: raw.updatedAt ?? now() } };
	}
	const keyOverride = pruneOverrides(raw.keyOverride, blocks);
	// Sections are derived: drop stale empties, regroup orphans by type.
	sections = sections.filter((s) => s.locked || s.blockIds.length > 0);
	if (Object.keys(blocks).length > 0) {
		const placed = new Set(sections.flatMap((s) => s.blockIds));
		const orphans = Object.keys(blocks).filter((id) => !placed.has(id));
		if (orphans.length > 0 || sections.length === 0) {
			const regrouped = autoGroup({
				mode, title: '', sections, blocks,
				keyOverride: {}, createdAt: '', updatedAt: ''
			});
			sections = regrouped.draft.sections;
		}
	}
	return {
		ok: true,
		draft: {
			version: BUILDER_SCHEMA_VERSION, mode,
			title: String(raw.title ?? ''), sections, blocks, keyOverride,
			createdAt: raw.createdAt ?? now(), updatedAt: raw.updatedAt ?? now()
		}
	};
}

function toBlockKeepId(id, b) {
	const paperId = typeof b.paperId === 'string' ? parseInt(b.paperId, 10) : b.paperId;
	const number = b.number != null ? String(b.number) : '';
	if (!isPid(paperId) || !number) return null;
	return {
		id,
		paperId,
		number,
		qtype: typeof b.qtype === 'string' && b.qtype ? b.qtype.slice(0, 20) : 'unknown'
	};
}

function pruneOverrides(ov, blocks) {
	const out = {};
	for (const [k, v] of Object.entries(ov ?? {})) {
		const bid = String(k).split(':')[0];
		if (blocks[bid] && typeof v === 'string') out[k] = v.slice(0, 200);
	}
	return out;
}
