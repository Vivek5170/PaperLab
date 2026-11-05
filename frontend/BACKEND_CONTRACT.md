# Backend contract for the Svelte frontend

Base URL: same-origin `/api` (dev proxy in `vite.config.js` forwards it to
`http://127.0.0.1:8000`). JSON everywhere unless noted.

## Auth (server session cookie, httpOnly)

- `GET /api/auth/me` -> `{authed: bool}`
- `POST /api/auth/login` `{password}` -> `204` + HttpOnly session cookie
- `POST /api/auth/logout` -> `204`

## Papers (public read; register/run are archivist-only)

- `GET /api/papers?query=&exam=` ->
  `[{id, title, exam, date, institute, status}]`
- `GET /api/papers/summary` ->
  `{counts: {paperId: n}, types: {paperId: "scq 4 - msq 3"}, buckets: {queued, running, done, failed}}`
- `GET /api/papers/meta` -> `{qtypes: [...], difficulties: [...]}`
- `GET /api/papers/{id}` -> `{id, title, exam, date, institute, status}`
- `GET /api/papers/{id}/questions` ->
  `[{number, qtype, difficulty, topics: [{code, path, auto}], question: [segments], solution: [segments]}]`
  Segment shapes: `{kind: "text", html}` (Python-Markdown HTML with math
  factored out; math pairing is the exact Streamlit `_split_math` rules),
  `{kind: "fig", url}` (never upscaled client-side: capped at 400px),
  `{kind: "table", header, rows}` with inline cells. Math arrives as
  `<span class="pl-math[data-tex]" data-display>` placeholders for the
  client to fill with KaTeX.
- `PATCH /api/papers/{id}/questions/{qn}`
  `{qtype?, difficulty?, topicCodes?, suggestion?}` (archivist)
- `DELETE /api/papers/{id}` -> `{paperId, deleted}` (archivist, hard-delete)
- `GET /api/papers/{id}/questions/{qn}/figures/{name}` -> image bytes
- `GET /api/papers/{id}/questions/{qn}/render?part=question|solution` -> compiled-TeX PNG (404 when the engine is unavailable)
- `POST /api/papers/register` `{pairs: [{question, solution|null}]}` (archivist)

## Tagging Inbox (archivist)

- `GET /api/inbox` ->
  `{total, items: [{paperId, number, qtype, difficulty, suggestion, topics: [{code, path, name, auto}]}]}` (light list, untagged only; fetch each question via `GET /api/papers/{id}/questions/{qn}`)
- `GET /api/papers/{id}/questions/{qn}` -> full single question (`number, qtype, difficulty, suggestion, topics, question + solution` segments)

## Topics (archivist for writes)

- `GET /api/topics` -> `[{code, parent, level, name, descr, rev}]`
- `POST /api/topics` `{parent, level, name, descr?}` (archivist)
- `PATCH /api/topics/{code}` `{name, descr, rev}` (archivist)
- `DELETE /api/topics/{code}` (archivist)
- `POST /api/topics/{code}/move` `{newParent}` (archivist)

## Stats / uploads / jobs (archivist)

- `GET /api/stats` ->
  `{totalCost, extraction, tagging, turns, rows: [{paper, status, turns, input, cached, output, reasoning, wall, extraction, tagging, total}], phases: [...]}`
- `GET /api/uploads` -> `{staged: [name]}`
- `POST /api/uploads` multipart `files[]` -> `{saved: [name]}`
- `DELETE /api/uploads` `{names}` 
- `GET /api/uploads/pairs/suggest` -> `{pairs: [{question, solution|null}], solutions: [name]}`
- `DELETE /api/uploads/clear` -> `{deleted: [name]}`
- `GET /api/jobs` -> `[{key, status, info}]`
- `POST /api/jobs` `{ids, mode: "sequential"|"parallel", force}`

## Figures (archivist; all reuse app/figures.py + verify_latex_syntax)

Trash files live in `figures/` as `_trash_<ts>_<name>` (invisible to
`list_figures`, which skips `_` prefixes). Crop/replace back up first;
delete strips refs (LaTeX-validated) then moves to trash; restore refuses
when the name is taken; only empty-trash unlinks.

- `GET /api/papers/{id}/questions/{qn}/figures` -> `[{name, side, usedIn, mode, url, width, height}]`
- `GET .../figures/trash` -> `[{name, original, keptAt}]`
- `POST .../figures` multipart (`file`, `target=question|solution`, `filename?`) -> figure (validates image, attaches ref, rolls back on bad LaTeX)
- `PATCH .../figures/{name}` `{left,top,right,bottom}` fractions -> figure (backs up first)
- `PUT .../figures/{name}` multipart `file` -> figure (same name, refs untouched)
- `DELETE .../figures/{name}` -> `{deleted, trash, wasUsedIn}`
- `POST .../figures/{name}/restore` -> figure (409 when the name is taken)
- `DELETE .../figures/trash/{name}` -> `{deleted}` (the only irreversible op)

## Mapping notes (from current Streamlit code)

- Library buckets: `app/library.py:bucket_papers`; fuzzy filter: `filter_papers`.
- Pairing: `app/pairing.py:auto_pair`, `split_candidates`, `register_pair`.
- Queue: `app/app.py:_untagged_queue` (SQL in one query).
- Stats: `summarize_tokens` in `run_pipeline.py` + `config.PRICING`.
- Runs: `app/runs.py:RunRegistry` maps naturally to a job table + SSE polling.
- TeX rendering: `app/render.py` `split_tex`/`tex_to_markdown` should move to an
  endpoint returning pre-split segments (`text` markdown / `fig` URL / `table`),
  so the Svelte client never parses LaTeX itself.
