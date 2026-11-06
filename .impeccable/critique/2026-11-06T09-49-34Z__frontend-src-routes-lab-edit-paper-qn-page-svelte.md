---
target: TeX editor workspace
total_score: 18
max_score: 40
na_heuristics: 
p0_count: 2
p1_count: 2
target_identity: "file:/Users/vivek/Codes/UltimateDatabase/Idk/frontend/src/routes/lab/edit/[paper]/[qn]/+page.svelte"
target_fingerprint: "sha256:ff20e19528f9d9e24b0c2580bc359d1b5e10d9c6c491395f73cc3e1b434d9ba6"
target_path: /Users/vivek/Codes/UltimateDatabase/Idk/frontend/src/routes/lab/edit/[paper]/[qn]/+page.svelte
timestamp: 2026-11-06T09-49-34Z
slug: frontend-src-routes-lab-edit-paper-qn-page-svelte
---
# Critique: TeX editor workspace (lab/edit/[paper]/[qn])

Method: dual-agent (A: ses_e4fbdb81fffeoXVLZ0GklbRFTB · B: ses_e4fbdb81bffeyM79qNuuOq0JAQ). Detector: 0 findings. Browser: unavailable (no tooling), static a11y facts used as fallback.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Status pill lies "Saved" before load; preview errors hide in small sub text |
| 2 | Match System / Real World | 3 | Solid archivist language; occasional jargon |
| 3 | User Control and Freedom | 1 | File switch traps into discard-only dialog, wipes both drafts |
| 4 | Consistency and Standards | 2 | Copy-figures looks like a file tab, behaves as a menu |
| 5 | Error Prevention | 1 | Destructive dialog primary; one-click Discard; manual 409 recovery |
| 6 | Recognition Rather Than Recall | 2 | Figure context hover-only; paste target must be recalled |
| 7 | Flexibility and Efficiency | 1 | Only Ctrl+S; no find, no insert-at-cursor, no save-all |
| 8 | Aesthetic and Minimalist Design | 3 | Appropriately spartan; mobile header crowds |
| 9 | Error Recovery | 2 | beforeunload missing returnValue; 409 means retyping |
| 10 | Help and Documentation | 1 | No explainer, no shortcut legend |
| **Total** | | **18/40** | **Poor** |

## Design Specificity Verdict

LLM assessment: authored for PaperLab but thinly. Reader-fidelity preview (same Segments renderer, 17.5px/1.7 type, question.tex/solution.tex naming, Copy-figures wired to listFigures, sha/409 conflict copy) is domain-specific. The editing core is an interchangeable bare textarea with no TeX-aware affordance. Tokens inherited correctly from app.css.
Deterministic scan: `impeccable detect` returned [] (0 findings). No overlay available; no browser verification performed.

## Overall Impression

The workspace earns trust fast (familiar tokens, honest WYSIWYG preview, real concurrency guard) and then spends it at exactly the archivist's core loop: moving between question and solution threatens to destroy work, and saving during typing can silently mark unsaved text as saved. Fix the save/switch safety, and this is a Good surface.

## What's Working

1. Preview fidelity intent: same Segments renderer and card styles, explicit "Live render · reader styles" label sets the right mental model.
2. Concurrency honesty: expectedSha + distinct 409 copy instead of silent overwrite.
3. Dirty guardrails: intercepted Back, beforeunload, per-part edited flag, disabled Save when clean.

## Priority Issues

### 1. (P0) Saving while typing or switching can mark unsaved text as saved
The save handler re-reads live drafts/part after await; keystrokes typed mid-flight become "baseline" while disk holds older bytes, and 409 never fires. Nothing disables the editor during save, and typing clobbers the saving flag enabling double-submit. Fix: snapshot part+text before await, disable editor/switch/discard while saving, promote baseline only if drafts still equal the snapshot. Suggested command: $impeccable harden.

### 2. (P0) Switching files discards both drafts with no save-and-switch
The core archivist loop (question ↔ solution cross-check) is punished with data loss; the topbar Discard resets only the current part, so behavior is inconsistent. Fix: three-button dialog (Save & switch / Discard & switch / Keep editing), primary on the safe action, reset only what the user chose. Suggested command: $impeccable harden.

### 3. (P1) Unsaved-changes dialog defaults to destruction
Discard changes is the seal-red primary; Esc does nothing; no focus trap or initial focus. Fix: primary on Keep editing (or Save & continue), Esc cancels, focus heading on open, trap Tab, return focus to invoker. Suggested command: $impeccable polish.

### 4. (P1) Preview failure and loading states are buried
Errors render as small panehead sub text, part switch flashes an empty pane, and the editor just greys with no skeleton during load. Fix: dedicated preview banner with Retry, skeleton while loading, keep old segments until the new preview resolves, pass zoomable for reader parity. Suggested command: $impeccable polish.

### 5. (P2) Copy-figures is a tab that behaves like a menu
Sitting inside the Question|Solution pill sets a mode expectation it breaks; copy-to-clipboard leaves the paste burden (cursor, target file) on memory. Fix: insert the snippet at the textarea cursor, keep focus, show usedIn visibly in the menu. Suggested command: $impeccable polish.

## Persona Red Flags

Alex (power user): discard wall when polishing Q+S together; save covers one part only; Ctrl+S no-ops silently unless dirty; no keyboard file switch, no find, line count without cursor position.
Sam (keyboard/SR): seg and mobile tabs lack aria-pressed/tablist semantics; usedIn tooltip-only; whole preview pane is aria-live so every keystroke pause re-announces the question; dialog has no focus management; status+toast double-announce; seg/menu targets under 24px.
Casey (mobile): sticky header wraps to 3-4 rows; Editor/Preview tabs force blind typing with tab-flipping per brace; switch yanks back to Editor tab; horizontal textarea panning; toast covers the editor; menu min-width overflows 320px screens.

## Minor Observations

- Status reads "Saved" before either file loads; no loading skeleton.
- No h1 in the workspace; Experimental badge has no explainer.
- Toasts overwrite each other (save + copy share one timer, 3.2s, no stacking).
- Switching parts clears segments before the new preview resolves (flash).
- backHref silently falls back to /archive for any non-/search origin.

## Questions to Consider

- If this is an Operate tool for trained archivists, why does switching files threaten to destroy work — should Save & switch be the default?
- If the preview must resemble the reader, why drop the reader's zoomable figures — what would make preview the source of truth?
- Is a plaintext textarea plus clipboard-copy actually faster than the old pipeline, or does it move the load onto working memory?

## Reliability audit cross-notes (separate track, same branch)

An independent code audit confirmed two backend criticals behind this UI: same-second saves overwrite the .bak backup (unique names needed), and save is non-atomic write_bytes (temp-file + os.replace needed). It also independently flagged the save race, beforeunload returnValue, and 409-substring matching above. No router conflicts, no traversal holes, no figure-URL leakage found.
