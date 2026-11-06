/**
 * Block-level pagination (pure): pack rows into fixed A4 pages without
 * ever splitting a row. Oversized single rows get their own page.
 * Rows flagged keepWithNext never strand alone at a page bottom
 * (shifted forward): section headers, passage headings, question stems.
 * The de-orphan pass runs to fixpoint with capacity checks, so the
 * receiving page can never overflow into clipping.
 */
export const PAGE_W = 794; // A4 width @96dpi (CSS px == print px)
export const PAGE_H = 1123; // A4 height @96dpi
export const PAD_TOP = 48;
export const PAD_BOTTOM = 72; // incl. folio room
export const usableHeight = () => PAGE_H - PAD_TOP - PAD_BOTTOM;

/**
 * @param items [{id, h, keepWithNext?, breakBefore?}] in document order
 * @param usable max content px per page
 * @returns array of pages, each an array of ids
 */
export function packRows(items, usable) {
	const byId = new Map(items.map((it) => [it.id, it]));
	const pages = [];
	let cur = [];
	let used = 0;
	const push = () => {
		if (cur.length) pages.push(cur);
		cur = [];
		used = 0;
	};
	for (const it of items) {
		const h = Math.max(0, it.h ?? 0);
		if (cur.length && (it.breakBefore || used + h > usable)) push();
		cur.push(it.id);
		used += h;
	}
	push();
	// De-orphan to fixpoint: a page ending in a keepWithNext row hands it
	// forward, cascading any overflow the receiver can't hold.
	const heightOf = (ids) =>
		ids.reduce((s, id) => s + Math.max(0, byId.get(id)?.h ?? 0), 0);
	let moved = true;
	while (moved) {
		moved = false;
		for (let p = 0; p < pages.length; p++) {
			const page = pages[p];
			if (page.length <= 1) continue;
			const last = byId.get(page[page.length - 1]);
			if (!(last && last.keepWithNext)) continue;
			page.pop();
			if (p + 1 < pages.length) pages[p + 1].unshift(last.id);
			else pages.push([last.id]);
			moved = true;
			// Cascade: receiver over capacity pushes its own tail forward.
			let q = p + 1;
			while (q < pages.length && heightOf(pages[q]) > usable) {
				const tail = pages[q].pop();
				if (q + 1 < pages.length) pages[q + 1].unshift(tail);
				else pages.push([tail]);
				if (pages[q].length === 0) pages.splice(q, 1);
				else q++;
			}
			break; // restart scan: new tail of page p may also orphan
		}
	}
	return pages.filter((pg) => pg.length > 0);
}
