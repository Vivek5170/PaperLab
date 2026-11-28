# EJEE Importer app

A small local app, separate from PaperLab, that converts EJEE content into
PaperLab papers without the command line:

1. **Search EJEE**: every question in the EJEE database: textbooks,
   institute study material and test papers (Allen, Sri Chaitanya, FIITJEE…),
   past-year and exam papers, olympiads. Filter by category, source, type,
   difficulty, exam, year, EJEE topic, answer content and status. The split
   view (⫴ in the top bar) shows the results on the left and the original
   pages on the right.
2. **Convert Books**: every source as one card with its progress.
   **Convert book** puts all remaining parts (or a range such as `1-5`) in
   the cart.
3. **Cart**: 15-question parts. Each part becomes one PaperLab paper,
   `<Book> — Part N`, the same part `run_book.py` would convert.
4. **Process & Publish**: transcribe, crop, tag, verify, bundle and upload
   each part to your PaperLab server through its archivist bundle API.
   No review or approval step: parts go straight through.
5. **Settings**: PaperLab server link, archivist password, Meta API key,
   EJEE database and uploads folder.

Everything listed is convertible; there is no exclusion list in this app.
(The command-line `run_book.py` keeps its own exclusion list.) Teaching
slides are not questions and are not listed. A few EJEE rows cannot be
converted by anyone because EJEE itself lacks the data (image file missing,
no body box, a solution without its question); they are not listed, and
Settings shows how many there are.

It uses PaperLab's look (same palette, fonts and components) but does not
import PaperLab's `backend/` or `frontend/`. The server only ever receives
`.plbundle` files through `POST /api/bundles/import`, as
[AGENTS.md](../../AGENTS.md) requires.

## Run

Install PaperLab's Python requirements once
([main guide](../../README.md#2-install-and-configure)) and Node.js 24, then
from the repository root:

**macOS / Linux**

```sh
npm --prefix importer_EJEE/app/web ci
npm --prefix importer_EJEE/app/web run build
.venv/bin/python importer_EJEE/app/server.py
```

**Windows (PowerShell)**

```powershell
npm.cmd --prefix importer_EJEE/app/web ci
npm.cmd --prefix importer_EJEE/app/web run build
.\.venv\Scripts\python.exe importer_EJEE/app/server.py
```

Open **http://127.0.0.1:8030/** (`--port` changes it, `--open` opens the
browser). Rebuild the UI after updating the code. The app listens on
loopback only and refuses any other host: it holds a paid API key and the
archivist password. For a deliberate demo behind a tunnel or proxy, add
`--public-host exact.host.name` (repeatable, or `EJEE_APP_PUBLIC_HOSTS`);
anyone who reaches that name can spend the key and publish, so stop the
app or the tunnel when the demo ends.

For UI development, run the server as above and
`npm --prefix importer_EJEE/app/web run dev`, then open
http://127.0.0.1:5174/.

## First run

1. **Settings → EJEE source**: the database file and uploads folder of an
   authorized EJEE copy. Saving valid paths builds the search index once in
   the background (about 4 minutes for 160k rows; progress is shown). The
   app never writes to the EJEE files.
2. **Settings → PaperLab server**: the server link (`https://…`, or
   `http://127.0.0.1:8000` for a PaperLab on the same computer) and the
   archivist password. **Save & test connection** logs in and out again.
   The server must allow bundle imports (non-default archivist password;
   see the [bundle guide](../../paperlab_bundle/README.md#upload-to-a-deployed-server)).
3. **Settings → Meta API**: your key. **Save & test key** asks the model
   endpoint's free `/models` listing; a rejected key is reported at once.

**Faster with more keys.** Settings → Meta API → *Extra keys for parallel
processing* takes more keys (one per line, ideally from different accounts).
Each key runs its own worker on the same ordered queue, so three keys are
roughly three times faster. A rejected key is set aside until you press
Resume; a rate-limited one is retried after 15 minutes; the others keep
going. PaperLab accepts one upload at a time, so parallel uploads wait
their turn instead of pausing the queue.

Search, books and cart work without the key or the server. **Processing
stays locked until all five settings are set**, and Start/Resume first
re-check the server login and the key, both without cost, so a wrong
setting is caught before any paid call.

## Processing and safe failure

Steps per part: Prepare → Transcribe → Figures → Pack → Tag topics →
Verify → Bundle → Publish. Each part records the steps it finished, and a
resume always continues at the first unfinished step. Run folders are the
same `importer_EJEE/runs/books/<book>/part-NNN/` that `run_book.py` uses, so
the app and the CLI can continue each other's work.

**Direct publishing.** The importer holds a figure when its crop touches an
edge or used up its crop attempts, and PaperLab's upload API refuses
bundles with unapproved holds. The app therefore records an approval
itself, by `EJEE Importer app (automatic, no human review)`, verifies
again and publishes. That wording travels in the bundle's provenance, and
the Process page lists the questions published this way. Real verification
problems (an unfinished question, invalid TeX, a missing figure) are not
approved: the part fails with the reason.

| What goes wrong | What happens | What you do |
|---|---|---|
| Meta key rejected, model endpoint unreachable, rate limit or quota | The **queue pauses** with the reason; the part stays at that step. Finished questions are kept and never billed again. | Fix the key (or wait), press **Resume**. |
| PaperLab link wrong, server down, wrong password, server busy | The queue pauses at **Publish**. The exported bundle is kept unchanged. | Fix Settings, press **Resume**. The same bytes are re-sent, so a lost reply cannot create a duplicate: the server returns the original receipt. |
| A question still fails after one automatic retry, or verification finds real problems | Only that part fails, with the reason; others continue. | **Retry** re-runs only the unfinished questions. |
| The app is closed mid-step | On the next start the interrupted part is queued again and the queue stays paused. | Press **Resume**. |

Pause stops after the current step. Removing a part from the list keeps
its run folder; adding it again resumes from there. Each part shows its
measured cost in USD, INR and INR including 18% GST (₹92.89/USD; the
`USD_INR` environment variable overrides it). The cart and book cards show
an estimate from the measured pilot range in
[EJEE_SOURCES.md](../EJEE_SOURCES.md) §4.

## Where things are kept

| Path | Contents |
|---|---|
| `importer_EJEE/app/data/` (override `EJEE_APP_DATA`) | `state.db` (settings, cart, jobs), `secrets.json` (key and password, owner-only permissions), `index.db` (search index), `thumbs/` (preview cache). Not in Git. |
| `importer_EJEE/runs/books/` (override `EJEE_APP_RUNS`, relative to `importer_EJEE/`) | Frozen book plans and part runs, shared with `run_book.py`. |

The key is passed to the importer in memory only; it is never written to
`.env`, logs or the browser. The browser sees whether a secret is set and
its last four characters. Every state-changing request must carry the
app's own header, and cross-origin requests are refused, so other web
pages cannot drive the app.

## Files

| File | Role |
|---|---|
| `server.py` | FastAPI app, loopback guard, API, serves the built UI |
| `ejee_index.py` | Index of every EJEE question, categories, parts, books, search and facets |
| `pipeline.py` | Processing queue, failure classification, direct-mode approval |
| `remote.py` | PaperLab bundle API client and Meta key probe (standard library) |
| `store.py` | Settings, secrets, cart and job state |
| `images.py` | Read-only previews of EJEE source images |
| `web/` | SvelteKit UI (static build) |

Tests: `python scripts/test_backend.py -q` includes
`importer_EJEE/tests/test_app.py` (synthetic EJEE database, fake PaperLab
server, no model key).
