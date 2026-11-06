/**
 * Split text-segment HTML into top-level flow blocks (pure). Each
 * paragraph, list or other block becomes one independently measurable
 * pager row, so pages fill tightly instead of stranding half empty.
 * Containers (<ol>/<ul>/<table>/...) never split: nested items stay
 * whole, which also keeps option groups together.
 */

const CONTAINERS = new Set([
	'ol', 'ul', 'table', 'thead', 'tbody', 'tr', 'blockquote', 'div', 'li',
	'details', 'figure', 'dl'
]);
const BLOCKS = new Set([
	'p', 'ol', 'ul', 'table', 'blockquote',
	'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'hr'
]);
const VOID = new Set(['img', 'br', 'input', 'source', 'wbr']);

/**
 * @param html text-segment HTML
 * @returns array of top-level block HTML strings, in order
 */
export function splitTopBlocks(html) {
	const out = [];
	let depth = 0;
	let start = 0;
	const re = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>/g;
	let m;
	while ((m = re.exec(html)) !== null) {
		const closing = m[1] === '/';
		const tag = m[2].toLowerCase();
		if (VOID.has(tag)) continue;
		if (!closing && /\/>$/.test(m[0])) continue; // self-closed
		if (!closing && CONTAINERS.has(tag)) {
			depth++;
			continue;
		}
		if (closing && CONTAINERS.has(tag)) {
			depth = Math.max(0, depth - 1);
			if (depth > 0 || !BLOCKS.has(tag)) continue;
		} else if (!closing || depth > 0 || !BLOCKS.has(tag)) {
			continue;
		}
		// Top-level block close (or self-contained block element).
		const end = m.index + m[0].length;
		const chunk = html.slice(start, end).trim();
		if (chunk) out.push(chunk);
		start = end;
	}
	const tail = html.slice(start).trim();
	if (tail) out.push(tail);
	return out;
}
