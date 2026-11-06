/**
 * Block-level pagination (pure): pack rows into fixed A4 pages without
 * ever splitting a row. Oversized single rows get their own page.
 * Rows flagged keepWithNext never strand alone at a page bottom
 * (shifted forward): section headers, passage headings, question stems.
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
	// De-orphan: a page ending in a keepWithNext row hands it forward.
	for (let p = 0; p < pages.length; p++) {
		const page = pages[p];
		const last = byId.get(page[page.length - 1]);
		if (page.length > 1 && last && last.keepWithNext) {
			page.pop();
			if (p + 1 < pages.length) pages[p + 1].unshift(last.id);
			else pages.push([last.id]);
		}
	}
	return pages.filter((pg) => pg.length > 0);
}
