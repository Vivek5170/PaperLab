# Portable author test dataset

`paperlab.db` is a ready-to-read PaperLab database. All files referenced by its question rows and paper PDFs are included. Paths are portable relative paths; use the launcher below to copy/rebase them into a writable review directory before starting the application.

| Paper | Textbook | Chapter | Questions | Scope |
|---|---|---|---:|---|
| 1 | David Morin, Introduction to Classical Mechanics | 1: Strategies for solving problems | 18 | Full chapter question set |
| 2 | David Morin, Introduction to Classical Mechanics | 2: Statics | 2 | Questions 2.1–2.2 only |
| 3 | Hibbeler, Engineering Mechanics: Dynamics, 14e | 12: Kinematics of a Particle | 2 | Questions 12–1 and 12–5 only |

There are 22 questions, seven isolated diagram PNGs, eleven supplied worked solutions and eleven explicit missing-solution placeholders. All 22 questions were classified freshly by upstream Node 3. One question has a taxonomy-gap suggestion instead of an unrelated forced topic. Native usage rows contain 72 extraction turns and 22 classification turns, rather than fabricated historical usage.

## Browse without AI calls

From a normal PaperLab checkout containing this importer:

```powershell
python -m venv importer_EJEE/.venv
importer_EJEE/.venv/Scripts/python.exe -m pip install -r importer_EJEE/requirements.txt
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/serve_sample.py --port 8001
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173/archive. Port 8001 matches the upstream Vite API proxy. Use unused ports or stop a separately running dev instance before launching. No Meta key is needed just to browse. The bundled database is copied into `importer_EJEE/runs/sample-review`; it is not used as the production database. Subsequent launches retain edits in that review copy.

On macOS/Linux, use `importer_EJEE/.venv/bin/python` in place of the Windows executable paths.

## Reproduce conversion

Set your own `META_API_KEY` via the normal PaperLab environment/.env. Then choose one included config:

```powershell
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py prepare --config importer_EJEE/sample_data/configs/morin-chapter-02-sample.json
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py extract --config importer_EJEE/sample_data/configs/morin-chapter-02-sample.json
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py figures --config importer_EJEE/sample_data/configs/morin-chapter-02-sample.json
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py classify --config importer_EJEE/sample_data/configs/morin-chapter-02-sample.json
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py pack --config importer_EJEE/sample_data/configs/morin-chapter-02-sample.json
importer_EJEE/.venv/Scripts/python.exe importer_EJEE/importer.py verify --config importer_EJEE/sample_data/configs/morin-chapter-02-sample.json
```

Reproduction makes paid API calls; browsing and tests do not. `ejee_sample.db` plus `source_assets/` supplies only selected input records. `configs/` identifies exact chapter groups. `provenance/` retains original metadata for tracing content; it is not required for the reader UI. `data/sources/` (EJEE body images and synthetic image PDFs, not full textbook PDFs) is author-local and not committed — re-running `extract`/`figures` needs it on disk, but browsing, verification and tests do not.

## Content attribution

Printed problem/solution excerpts remain the work of their respective textbook authors/publishers. Inclusion as test data does not relicense those third-party texts or imply that the textbooks are open source merely because PaperLab is. No new copyright license is asserted over those excerpts. The fixture is explicitly separated from importer code so maintainers can replace or remove it independently.
