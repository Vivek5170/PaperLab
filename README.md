# 📖 PaperLab — Physics Paper Extraction Tool

Turns physics question-paper PDFs (JEE / NEET style) into a clean, searchable
library. Upload PDFs → AI extracts every question into LaTeX with cropped
figures → read everything in the Library. Admin area handles uploads, runs,
costs, and figure fixes.

Pick **ONE** setup option below. Run everything from inside the `Idk` folder.

---

## 0. You need (both options)

- **Python 3.10+** ([python.org](https://www.python.org/downloads/);
  on Windows tick **"Add python.exe to PATH"**), **Git**, internet.
- **Meta API key** — ask the project owner, or grab one from the Meta API console.
- *(Optional)* **Tectonic** ([installers](https://tectonic-typesetting.github.io/en-US/install))
  — only for the "Render as image" button; everything else works without it.

```bash
git clone <paste-the-repo-url-here>
cd Idk
```

---

## A. Setup with `uv` (recommended)

Install `uv` once: Mac → `curl -LsSf astral.sh/uv/install.sh | sh`
(Mac) · Windows PowerShell →
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
(reopen the terminal after).

| Mac | Windows PowerShell |
|---|---|
| `uv venv` | `uv venv` |
| `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| `uv pip install -r requirements.txt` | `uv pip install -r requirements.txt` |

## B. Setup with plain `.venv`

| Mac | Windows (`cmd`) |
|---|---|
| `python3 -m venv .venv` | `py -m venv .venv` |
| `source .venv/bin/activate` | `.venv\Scripts\activate` |
| `pip install -r requirements.txt` | `pip install -r requirements.txt` |

> You must see `(.venv)` in your terminal — redo the `activate` line in every
> new terminal. Blocked script on Windows? Run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

---

## Keys, run, first paper

```bash
# Mac: cp .env.example .env | Windows cmd: copy .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
```

Edit `.env` (any text editor) and set:
```ini
META_API_KEY=sk-paste-your-real-key-here
PAPERLAB_ADMIN_PASSWORD=choose-a-strong-password   # default is "admin" — change before hosting
```

```bash
streamlit run app/app.py     # opens http://localhost:8501 (Ctrl+C to stop)
```

1. Click **🔒 Admin** (top right), log in.
2. **🛠 Admin → 📥 Upload & Processing**: *Stage files* → confirm pairs → tick the paper → **Run** (takes a few minutes, page refreshes itself).
3. **📖 Library**: open the paper, flip through questions. Admins can fix figures under *Manage figures*.

PDFs move themselves: `data/uploads/` → `data/processing/` → `data/archive/`.
Don't touch `data/` mid-run.

---

## If something goes wrong

| Symptom | Fix |
|---|---|
| `streamlit: command not found` / `ModuleNotFoundError` | Activate `.venv` first, then install requirements again |
| `META_API_KEY is ... placeholder` | You didn't edit `.env` |
| `Port 8501 is already in use` | App already runs in another terminal |
| `Render as image` fails | Install Tectonic (optional; KaTeX view still works) |
| Paper stuck on "Running" after restart | It was marked failed — just re-run it |

**Layout:** `app/app.py` = website · `app/figures.py` = figure tools ·
`database.py` = SQLite store · `graph.py` = the two AI agents ·
`run_pipeline.py` = CLI runner · `data/` + `Outputs/` = your files (auto-managed).

**Roadmap:** live LaTeX editor mode.
