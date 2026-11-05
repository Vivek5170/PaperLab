# PaperLab frontend (SvelteKit)

Modern Svelte replacement for the Streamlit UI in `app/`. Layout follows the
approved reference (sidebar + topbar + stat cards) re-skinned to the Archive
Reading Room tokens in `src/app.css` (which mirror `DESIGN.md`).

## Run

```sh
cd frontend
npm install
npm run dev      # http://127.0.0.1:5173, /api proxied to :8000
npm run build    # static output in build/
```

## Structure (best-practice SvelteKit)

```text
frontend/
  src/
    app.css                 # design tokens + base styles (light/dark)
    app.html
    lib/
      api.js                # REST client; 1:1 with BACKEND_CONTRACT.md
      stores.js             # theme, role, searchQuery (localStorage-backed)
      components/
        Sidebar.svelte      # brand, nav, status ledger, role switch
        Topbar.svelte       # breadcrumb, role pill, Ctrl+K search, theme toggle
        StatCard.svelte     # stat tiles
        PaperCard.svelte    # archive catalog card
        SegmentedTabs.svelte# pill tabs (Stage / Verify / Pipeline)
    routes/
      +layout.svelte        # shell: sidebar + topbar + content
      +page.svelte          # redirect to /archive
      archive/              # Archive wall (everyone)
      archive/[id]/         # Reading Desk (everyone reads; archivist edits)
      inbox/                # Tagging Inbox (archivist)
      syllabus/             # Syllabus Map (archivist)
      intake/               # Intake and Pipeline (archivist)
      ledger/               # Usage Ledger (archivist)
```

## Roles

`role` store (`student` | `archivist`) only hides edit UI. Real enforcement
must happen server-side on every admin endpoint — see BACKEND_CONTRACT.md.

## Backend status

The Python API does **not** exist yet. Until it does, pages render friendly
"backend unreachable" states and the Streamlit app (`streamlit run app/app.py`)
remains the working application.
