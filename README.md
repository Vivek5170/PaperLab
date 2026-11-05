# PaperLab — Physics Paper Extraction Tool

Turns physics question-paper PDFs (JEE / NEET style) into a clean, searchable
library. Upload PDFs → AI extracts every question into LaTeX with cropped
figures → browse in Archive, filter in Search Questions, tag in the Inbox.

Stack: **FastAPI backend** (`backend/`, port 8000) + **SvelteKit frontend**
(`frontend/`, port 5173 in dev). Run everything from inside the `Idk` folder.

---

## 0. You need

- **Python 3.10+** ([python.org](https://www.python.org/downloads/);
  on Windows tick **"Add python.exe to PATH"**), **Git**, internet.
- **Node 18+** ([nodejs.org](https://nodejs.org/)) — for the frontend.
- **Meta API key** — ask the project owner, or grab one from the Meta API console.
- *(Optional)* **Tectonic** ([installers](https://tectonic-typesetting.github.io/en-US/install))
  — only for the "Render as image" button; everything else works without it.

```bash
git clone <paste-the-repo-url-here>
cd Idk
```

---

## 1. Backend setup (once)

| Mac | Windows (`cmd`) |
|---|---|
| `python3 -m venv .venv` | `py -m venv .venv` |
| `source .venv/bin/activate` | `.venv\Scripts\activate` |
| `pip install -r requirements.txt` | `pip install -r requirements.txt` |

> You must see `(.venv)` in your terminal — redo the `activate` line in every
> new terminal. Blocked script on Windows PowerShell? Run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 2. Frontend setup (once)

```bash
cd frontend
npm install
cd ..
```

## 3. Keys (once)

```bash
# Mac: cp .env.example .env | Windows cmd: copy .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
```

Edit `.env` (any text editor) and set:

```ini
META_API_KEY=sk-paste-your-real-key-here
PAPERLAB_ADMIN_PASSWORD=choose-a-strong-password   # default is "admin" — change before hosting
```

Non-secret settings (model, paths, pricing) live in `config.yaml` and work
as-is; `.env` overrides them only when set (see `.env.example`).

---

## 4. Run (two terminals, every time)

Terminal 1 — API (must run from the repo root, `.venv` active):

```bash
python3 -m uvicorn backend.main:app --port 8000
```

Terminal 2 — frontend:

```bash
cd frontend
npm run dev -- --port 5173 --host 127.0.0.1
```

Open **http://127.0.0.1:5173**. The dev server proxies `/api` to the backend.

> Sessions live in server memory: restarting the API logs everyone out
> (just log in again). Running uvicorn from any other directory breaks imports.

### Production (single process)

```bash
cd frontend && npm run build && cd ..
python3 -m uvicorn backend.main:app --port 8000
```

When `frontend/build` exists, the API serves the built site itself —
open **http://127.0.0.1:8000** and skip terminal 2.

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
| Tagging Inbox | Classify untagged questions (archivist) |
| Syllabus Map | View/edit the topic tree (archivist for writes) |
| Intake and Pipeline | Upload, pair, register, run papers (archivist) |
| Usage Ledger | Token costs + reclaimable-disk cleanup (archivist) |

Search and reading are open to everyone; uploads, tagging, topics, ledger,
and figure management need the archivist login.

---

## 6. Verify / test

```bash
python3 -m pytest tests/ -q        # backend suite (from repo root, .venv active)
cd frontend && npm run build        # frontend build must pass
npm run smoke                       # SSR smoke check (from frontend/)
```

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
| `ModuleNotFoundError` / `uvicorn: command not found` | Activate `.venv` first, reinstall requirements |
| `META_API_KEY is ... placeholder` | You didn't edit `.env` |
| Frontend shows API errors / `401` | Backend not running, or wrong cwd — restart uvicorn from repo root |
| Logged out after restart | Expected — sessions are in-memory, log in again |
| Port already in use | Server already runs in another terminal |
| `Render as image` fails | Install Tectonic (optional; KaTeX view still works) |
| Paper stuck on "Running" after restart | It was marked failed — just re-run it |
| Search shows old page size / stale results | Hard-refresh (Cmd/Ctrl+Shift+R) to drop the saved state |

**Layout:** `backend/` = FastAPI routers · `frontend/src/routes/` = pages ·
`app/render.py` + `app/figures.py` = TeX/figure logic (reused, not rewritten) ·
`database.py` = SQLite store · `graph.py` = the two AI agents ·
`run_pipeline.py` = CLI runner · `data/` + `Outputs/` = your files (auto-managed).
