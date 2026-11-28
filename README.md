# PaperLab — Physics Paper Extraction Tool

Turns physics question-paper PDFs (JEE / NEET style) into a clean, searchable
library. Upload PDFs → AI extracts every question into LaTeX with cropped
figures → browse in Archive, filter in Search Questions, tag in the Inbox.

Stack: **FastAPI** API, **SQLite** storage, and a **SvelteKit** frontend.
**macOS and Linux are required deployment targets**, including headless
Linux servers. **Windows and Windows Server are supported on a best-effort
basis.**

---

## 1. What to download

| You want to… | What you need |
|---|---|
| Run the app, upload PDFs, or browse an existing archive | [Git](https://git-scm.com/downloads) to get the code, [Python 3.12](https://www.python.org/downloads/) and the packages in `requirements.txt`. Python includes SQLite; the packages include PDF handling. No separate database or PDF server. |
| Build or develop the frontend | [Node.js 24 LTS](https://nodejs.org/en/download) with npm. Node is needed where you **build**, not where you serve an already-built `frontend/build/`. Node 18 does not meet the frontend's dependency requirements. |
| Index, extract, or automatically tag questions | A project-authorized **Meta API key** and outbound access to the model endpoint. Browse, edit, build papers, print, and export without an AI key. |
| Print or save a PDF | Your **client browser**. In Paper Builder, click **Print / PDF**, then choose **Save as PDF** (or **Microsoft Print to PDF** on Windows). No browser or TeX install on the server. |
| Download editable Word files | The pinned **Pandoc** binary is installed by the Python requirements on macOS and Linux (x64 and arm64) and Windows (x64 Python). See [Word converter setup](#word-converter-setup) for other targets. Microsoft Word is not required on the server. |
| Use **Render as image** for TeX | Optional: install [Tectonic](https://tectonic-typesetting.github.io/en-US/install) **on the API host** and put its executable on `PATH`. The TeX bundle may download on first use. Normal KaTeX rendering and export do not use Tectonic. |

**Platform notes**

- **macOS:** Use the Python and Node installers for your Mac (Apple Silicon or
  Intel). `git --version` may prompt to install Apple's Command Line Tools.
  For optional TeX rendering, use Homebrew (`brew install tectonic`) or the
  [Tectonic releases](https://github.com/tectonic-typesetting/tectonic/releases).
- **Windows / Windows Server:** Install Python 3.12 x64 with the `py` launcher
  and install Node.js x64 and Git for Windows. On Windows on ARM, use x64
  Python under emulation and follow the [standalone Pandoc
  instructions](#word-converter-setup) if the wheel isn't selected. The
  PowerShell commands below use `.venv\Scripts\python.exe` and `npm.cmd`,
  so no execution-policy change is needed. For Tectonic, pick the Windows
  release and add the folder containing `tectonic.exe` to the API account's
  `PATH`.
- **Linux:** Use Python 3.12 with `venv` and a Node 24 distribution for your
  architecture. For example, on Ubuntu 24.04 install `git`, `python3`, and
  `python3-venv` with APT and get Node from the official download page.
  For Tectonic, choose the Linux release for your CPU and put it on `PATH`.

```bash
git clone https://github.com/Vivek5170/PaperLab.git
cd PaperLab
```

## 2. Install and configure

Run these commands from the checkout root.

**macOS / Linux**

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
npm --prefix frontend ci
```

**Windows (PowerShell)**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
npm.cmd --prefix frontend ci
```

If your platform doesn't ship Python 3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/)
can download it and create the venv: use `uv venv --python 3.12 --seed .venv`
in place of the first command, then continue with the same pip step.

Copy `.env.example` only on a fresh install; keep your existing `.env` when
upgrading. Set a strong archivist password before hosting. Leave `META_API_KEY`
blank unless you need the AI pipeline.

```ini
PAPERLAB_ADMIN_PASSWORD=choose-a-strong-password
META_API_KEY=
```

Configuration defaults live in `config.yaml`; `.env` or the process
environment can override them. Never commit `.env`.

### Word converter setup

On the supported wheel targets listed above, installing `requirements.txt`
is enough. If no wheel is available for your environment, get **Pandoc 3.9**
from the [official releases](https://github.com/jgm/pandoc/releases/tag/3.9)
or build that version from the official source, then set `PAPERLAB_PANDOC` in
`.env` to the absolute executable path. The override takes precedence over
the bundle. Use forward slashes in Windows `.env` paths.

```ini
# macOS/Linux example
PAPERLAB_PANDOC="/opt/pandoc/bin/pandoc"
# Windows alternative (set only one value)
# PAPERLAB_PANDOC="C:/Tools/Pandoc/pandoc.exe"
```

If Pandoc is missing or incompatible, **Download Word** reports that it's
unavailable; other features keep working. Word can reflow pages. Use
**Print / PDF** for the A4 preview layout, or if the converter reports math
it cannot include without losing content.

## 3. Build and run (production or local use)

Run the build once on install and after frontend updates. Start the API from
the checkout root. It serves the built frontend and API on the same port.
To keep Node off the server, build from the same Git revision on another
machine and copy the complete `frontend/build/` directory into the server's
checkout before starting the API.

**macOS / Linux**

```sh
npm --prefix frontend run build
.venv/bin/python -X utf8 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

**Windows (PowerShell)**

```powershell
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -X utf8 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. **http://127.0.0.1:8000/api/health** should
return `{"ok":true}`. On every platform, stop the foreground server with
`Ctrl+C`; restarting clears archivist sessions.

### Hosting on a server

- Run **one API process** under your OS service manager, as a non-admin
  account, with the checkout as its working directory. Use the full venv
  Python path from the commands above. Use `systemd` on Linux, `launchd` on
  macOS, or Task Scheduler on Windows (trigger **At startup**, set **Start
  in** to the checkout, and run whether or not the user is logged on).
  The server does not need a display.
  For **Render as image**, make sure the service account sees Tectonic on its
  `PATH` (`tectonic --version` in that environment).
- Keep port `8000` bound to localhost behind an HTTPS reverse proxy (for
  example Caddy, nginx, or IIS). Proxy both the site and `/api` to it on the
  same hostname. Set the proxy's upload limit to accommodate your intake
  PDFs. For `POST /api/export/docx`, allow up to 2 MiB, use an upstream
  timeout of at least 80 seconds for cold starts, and apply rate limits.
  Word conversion is also limited to one active request per API process.
- To enable [remote bundle imports](paperlab_bundle/README.md#upload-to-a-deployed-server),
  configure a strong, non-default `PAPERLAB_ADMIN_PASSWORD`. Enforce HTTPS at
  the proxy, pass the original `Host` and the proxy's `X-Forwarded-Proto`, and
  let Uvicorn trust forwarded headers **only** from the proxy's address
  (loopback by default). Rate-limit `/api/auth/login` and
  `/api/bundles/import`; don't log request bodies or cookies. Allow up to
  64 MiB for the bundle route and a proxy response timeout suitable for a
  full SQLite backup and merge (start with 10 minutes). Monitor free disk
  space and retain backups according to your recovery policy. Changing
  the archivist password requires restarting the API to revoke existing sessions.
- Give the service account write access to its SQLite file and its
  `Outputs/` and `data/` directories. Use persistent local storage, not an
  ephemeral container layer or a shared network filesystem for SQLite.
  Override paths with `PHYSICS_ARCHIVE_DB`, `PHYSICS_OUTPUT_BASE`, and
  `DATA_ROOT`; use absolute paths for services. Back up those three locations.
  When moving an existing archive to another machine, rebase and verify
  any absolute PDF paths stored in SQLite **before** starting the new API.

## 4. Develop with hot reload

Run the API command above on port `8000` in one terminal. In a second
terminal at the checkout root, run `npm --prefix frontend run dev -- --host
127.0.0.1` on macOS/Linux or `npm.cmd --prefix frontend run dev -- --host
127.0.0.1` in Windows PowerShell. Open **http://127.0.0.1:5173/**. The Vite
development server proxies `/api` to the API on port `8000`.

---

## 5. First paper

1. Click **Login** (top right), enter the admin password.
2. **Intake and Pipeline**: upload files → confirm question/solution pairs →
   register → tick the paper → **Run** (takes a few minutes).
3. **Archive**: open the paper, flip through questions. Admins can edit
   classification and fix figures (*Manage figures*; deletes go to trash first).

PDFs move themselves: `data/uploads/` → `data/processing/` → `data/archive/`.
Don't touch `data/` mid-run.

## Pages

| Page | What it's for |
|---|---|
| Archive | Browse papers and read questions |
| Search Questions | Filter by type, difficulty, exam, institute, year, topic (15 per page) |
| Cart | Collect questions and optionally compare the mix against a saved model paper |
| Paper Builder | Import a cart into an independent paper or assignment draft |
| Tagging Inbox | Classify untagged questions (archivist) |
| Syllabus Map | View/edit the topic tree (archivist for writes) |
| Intake and Pipeline | Upload, pair, register, run papers (archivist) |
| Usage Ledger | Token costs + reclaimable-disk cleanup (archivist) |

On the Cart page, open **Model papers** beside the role switch to create, edit,
or delete a named set of question counts. Select it in the cart to see what to
add or remove, or choose **None** to hide suggestions. Each paragraph passage
counts once toward its own paragraph type. The list starts with the
Physics-section structures of JEE Advanced 2014–2026 (2014 Paper 1 corrected
to 10 single-correct); paragraph targets count groups. Model papers and cart
selections stay in the current browser.

## Import books and papers

| Source | Start here |
|---|---|
| EJEE database and uploads | [EJEE importer](importer_EJEE/README.md): plan books into **15-question parts**, stage, review, and export. The separate [EJEE Importer app](importer_EJEE/app/README.md) does search → cart → process → publish in a browser. See the [13 live pilots and cost tables](importer_EJEE/EJEE_SOURCES.md) and [pilot handoff](importer_EJEE/STATUS.md). |
| Other textbook, worksheet, or paper | [Custom importer](custom_importer/README.md) for manual or agent-assisted transcription; send agents the [transcription skill](custom_importer/SKILL.md). |
| A portable `.plbundle` already exported | [PaperLab bundle guide](paperlab_bundle/README.md): inspect, dry-run, and merge through the local CLI or [the deployed archivist API](paperlab_bundle/README.md#upload-to-a-deployed-server). |

Both importers stage away from the archive and export the same bundle format.
Review before publishing. Archive merges take a SQLite backup, reject
duplicates, and preserve provenance. The operator performs the merge; there
is no bulk conversion, paid model call, or archive write just from installing
these tools.

Windows note: if organizational Application Control blocks a native Python
dependency such as `ormsgpack`, use an approved Python environment or run the
importer on macOS/Linux. Do not disable organizational policy.

Search and reading are open to everyone; uploads, tagging, topics, ledger,
and figure management need the archivist login.

### Reviewing automatic topic tags

Node 3 lists the main topic first and adds supporting topics only for
separate physics steps. Archivists can review the tags from a question's
**Edit classification** panel; the first saved topic is the main one.
The **Tagging Inbox** shows untagged questions and any explanation of why
the model could not tag them. A manual classification takes precedence
over later automatic runs.

Set the main-topic mode in `config.yaml` before starting a tagging run:

```yaml
topics:
  primary_mode: 2
```

- **`1` — AI order:** keep the main topic chosen by the model.
- **`2` — Teaching order (configured here):** make the latest of the model's
  selected topics the main one, using the course weeks in the [Sri Chaitanya
  Super-60 Nucleus 2026–28 schedule mapping](topics_teaching_order.json), not
  chapter numbers or the taxonomy's chapter-local week labels. For example,
  SHM follows fluid statics even though its chapter code is lower. Supporting
  tags keep their original order. If the latest week is tied, the first model
  pick in that week wins. All 296 built-in subtopics have a week; if a future
  code has no mapped week, keep the model's order rather than guessing.

The mapping uses teaching blocks, not cumulative tests, holidays or syllabus
eligibility notes. It records one week per code; for a topic split across
weeks, it favors the block teaching the code's distinguishing material
(for example, conservation of angular momentum over the initial definition).
Subtopics not clearly named in the schedule are listed separately under
`inferred_weeks` and placed with related material. For example, the
resonance-column experiment ranks with organ pipes and sound (W-36), and
legacy Communication Systems ranks with electromagnetic waves (W-55).
These placements are for ranking, not claims that the topics were taught
or included in an exam syllabus.

The question reader shows the saved main topic first, and Search's **Main
topics** filter uses that same saved tag. The setting does not change the
prompt, request extra model calls, or retroactively reorder saved tags.
The next tagging run reads the current value; future mode switches don't
require a server restart.
Resuming an EJEE conversion after changing the ranking configuration or
schedule can invalidate cached classifications and incur new model calls.

For a prompt release, keep the raw model results separate from review
corrections. Back up the database before publishing a bulk retag and
retain the prompt version, syllabus mapping, and original model replies
so reviewers can tell which classification the model actually made.

---

## 6. Verify / test

| Check | macOS / Linux | Windows PowerShell |
|---|---|---|
| Backend tests (isolated database, outputs and media) | `.venv/bin/python scripts/test_backend.py -q` | `.\.venv\Scripts\python.exe scripts/test_backend.py -q` |
| Frontend tests | `npm --prefix frontend test` | `npm.cmd --prefix frontend test` |
| Production build | `npm --prefix frontend run build` | `npm.cmd --prefix frontend run build` |
| Render smoke check (API running on port 8000) | `npm --prefix frontend run smoke` | `npm.cmd --prefix frontend run smoke` |

The [cross-platform workflow](.github/workflows/cross-platform.yml) runs the
backend tests (including real DOCX conversion), frontend tests and production
build on macOS, Linux and Windows. macOS and Linux checks must pass; Windows
checks run separately and are advisory. No AI key is needed. Tests requiring
untracked source PDFs are skipped on a fresh clone.

## Disk usage

Per paper: ~1 KB/question of `.tex` + ~57 KB/question of figures +
~2.7 MB of source PDFs. Render-cache PNGs and `data/cleaned/` intermediates
are regenerable — the **Usage Ledger** (bottom, archivist) shows both sizes
with delete buttons. Never delete: `physics_archive.db`, `Outputs/` figures
and tex, `data/archive/`, or the 2 DB-referenced `*_solsplit.pdf` files
(the ledger purge already excludes those).

---

## If something goes wrong

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` | Use the venv Python from the run commands and reinstall `requirements.txt` |
| `META_API_KEY is ... placeholder` | Set a valid `.env` key if you want to run indexing, extraction, or auto-tagging |
| Frontend shows API errors / `401` | Backend not running, or wrong cwd — restart uvicorn from repo root |
| Word export unavailable | Reinstall the Python requirements, or verify `PAPERLAB_PANDOC` and `pandoc --version` using the [Word setup](#word-converter-setup) |
| Logged out after restart | Expected — sessions are in-memory, log in again |
| Port already in use | Server already runs in another terminal |
| `Render as image` fails | Install Tectonic (optional; KaTeX view still works) |
| Paper stuck on "Running" after restart | It was marked failed — just re-run it |
| Search shows old page size / stale results | Hard-refresh (Cmd/Ctrl+Shift+R) to drop the saved state |

**Layout:** `backend/` = FastAPI routers · `frontend/src/routes/` = pages ·
`app/render.py` + `app/figures.py` = TeX/figure logic (reused, not rewritten) ·
`database.py` = SQLite store · `graph.py` = the two AI agents ·
`run_pipeline.py` = CLI runner · `data/` + `Outputs/` = your files (auto-managed).
