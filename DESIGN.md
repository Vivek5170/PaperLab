---
name: PaperLab
description: Physics extraction console - JEE / NEET archive reader
colors:
  paper: "#FAF7F0"
  paper-deep: "#EEE8D9"
  ink: "#1C1E21"
  ink-soft: "#5C6066"
  line: "#E0D9C8"
  seal-red: "#8C2F28"
  seal-red-deep: "#6E231E"
  pine: "#234E3E"
  paper-dark: "#16130E"
  surface-dark: "#201B14"
  ink-dark: "#EDE6D6"
typography:
  display:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "2rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "0em"
  title:
    fontFamily: "Source Serif 4, Georgia, serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.78rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.04em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "0.82rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  xs: "2px"
  sm: "4px"
  md: "6px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.seal-red}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  button-primary-hover:
    backgroundColor: "{colors.seal-red-deep}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  card:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "16px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  nav-item:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    padding: "10px 14px"
  nav-item-active:
    backgroundColor: "{colors.paper-deep}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    padding: "10px 14px"
  chip:
    backgroundColor: "{colors.paper-deep}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    padding: "2px 8px"
---

# Design System: PaperLab

## Overview

**Creative North Star: "The Archive Reading Room"**

PaperLab is an Operate + Read surface: operators process papers, readers study them. The new UI keeps Streamlit as the app shell but replaces default chrome with custom HTML/CSS: a catalog wall (library), a reading desk (question reader), and a back office (admin/upload/tree). Warm paper grounds, ink text, one seal-red accent used sparingly for primary action and active state.

Density is archival, not airy: compact rows, hairline rules, stamp-like labels, generous line-length control in the reading pane (65-75ch). Dark mode is a true second theme (late-night grading bench), not an inverted filter.

**Key Characteristics:**
- Warm paper light theme + true dark bench theme
- Editorial serif for paper/question titles only; system UI everywhere else
- Sharp archival corners (2-6px), hairline borders, flat at rest
- Custom HTML allowed: library cards, reader header, status ledger replace stock Streamlit cards
- Restrained color: accent on <=10% of any screen

## Colors

Restrained strategy: neutrals tinted warm paper plus one seal-red accent; status hues confined to the ledger and badges.

### Primary
- **Seal Red** (#8C2F28): primary action (Open, Run, Confirm pairs), active nav marker, 3px left rule on the open question. Rare by design.
- **Seal Red Deep** (#6E231E): hover/pressed state of primary; focus ring base.

### Secondary
- **Pine** (#234E3E): success/ledger "done" and tagging confirmations only. Never a second button color.

### Tertiary
- **Ochre** (ledger warning text, #8A6D1B on light / #D9B64A on dark): failed/attention states in the status ledger only.

### Neutral
- **Paper** (#FAF7F0): app ground (light).
- **Paper Deep** (#EEE8D9): active nav, selected question, input fill on focus.
- **Ink** (#1C1E21): body text, headings.
- **Ink Soft** (#5C6066): captions, metadata, provenance lines.
- **Hairline** (#E0D9C8): 1px rules, card borders, table dividers.
- **Paper Dark** (#16130E) / **Surface Dark** (#201B14) / **Ink Dark** (#EDE6D6): dark-theme ground, raised surface, text.

### Named Rules
**The One Seal Rule.** Seal red appears on at most one element per viewport region (one primary button, one active nav item, one open-question marker). Its rarity is the point.
**The Ledger Rule.** Red/green/amber status hues live only in the status ledger, badges, and metric deltas - never as button fills or body text.

## Typography

**Display Font:** Source Serif 4 (with Georgia fallback)
**Body Font:** Inter, system-ui (workhorse UI face)
**Label/Mono Font:** ui-monospace stack (IDs, counts, token figures, file names)

**Character:** Titles read like catalog entries - serif, tight, confident. Everything operable reads like an instrument label - small, uppercase-tracked or mono, unambiguous.

### Hierarchy
- **Display** (600, 32px/1.15): paper title on the reader page only. Serif.
- **Headline** (600, 20px/1.3): page titles (Library, Processing, Needs topics). Serif.
- **Title** (600, 16px/1.3): library card title, question heading (`Question 15a`). Serif for card/question; system semibold for panel titles.
- **Body** (400, 15px/1.55, max 65-75ch in reading pane): question/solution prose, captions expanded, form help.
- **Label** (600, 12.5px, +0.04em tracking, uppercase for eyebrows): eyebrows (`QUESTIONS`, `PROVENANCE`, `BACKGROUND JOBS`), button text, tab text.
- **Mono** (400, 13px/1.5): paper IDs (`#42`), counts, token tables, file paths, TeX fallback notes.

### Named Rules
**The Two-Voice Rule.** Serif speaks the archive (titles, questions). System/mono speaks the instrument (actions, metadata, numbers). They never swap jobs.
**The 75ch Rule.** Reading-pane prose never exceeds 75ch; wider viewports add margin, not longer lines.

## Layout

Two-region Operate shell + focused Read pane, custom HTML grid over Streamlit:

- **Shell:** fixed left rail (264px desktop, collapses to top bar under 900px) holding brand plate, nav (Archive / Tagging Inbox / Syllabus Map / Intake and Pipeline / Usage Ledger, back-office four grouped under a WORKSHOP divider), and a 4-cell status ledger (done / queued / running / failed). Students see Archive only plus a `Workshop locked - admin login required` line; edit UI is never rendered for students, not merely disabled. Content column max 1120px, 24px gutters.
- **Archive (was Library):** card wall, 1 column (each card: serif title, mono meta line, type chip row, source row with inline Download text-button). Card = 1px hairline, 6px radius, 16px padding; 16px gaps.
- **Reader:** 280px question index + fluid reading pane. Index collapses to a `Question` select above 40 questions (already implemented). Prev/Next/Jump bar pinned under the pane, min 44px targets.
- **Admin:** tabbed back office (Statistics / Upload and Processing); danger zone bottom, confirm-gated.
- **Responsive:** rail to top bar <900px; reader index to select <760px; library stays single column (no multi-column squeeze); tables scroll-x inside cards, never page-scroll.
- **Dark mode:** same grid; ground swaps to Paper Dark, cards to Surface Dark, hairline to #3A332A, accent holds (lightened to #C25A4E for AA on dark).

## Elevation & Depth

Hybrid: flat at rest, lifted on response.

No resting shadows. Depth comes from tonal layering (Paper vs Paper Deep) and 1px hairlines. Shadow appears only as a response: card hover (ambient-low), open dialog/expander (ambient-high), focused input (focus ring, no shadow).

### Shadow Vocabulary
- **Ambient low** (`box-shadow: 0 1px 2px rgba(28,30,33,0.08), 0 4px 16px rgba(28,30,33,0.08)`): library card hover, question index hover.
- **Ambient high** (`box-shadow: 0 8px 32px rgba(28,30,33,0.18)`): admin login dialog, figure re-crop sheet, toast stack.
- **Focus ring** (`outline: 2px solid #8C2F28; outline-offset: 2px`): all interactive elements on `:focus-visible`. Dark theme uses #C25A4E.

### Named Rules
**The Flat-By-Default Rule.** Surfaces are flat at rest. A shadow that exists without hover, focus, or dialog state is a bug.
**The One-Line Depth Rule.** Borders are always 1px Hairline; depth steps change tone or shadow, never border weight.

## Shapes

Sharp archival form language: small radii, straight rules, stamp-like tags.

- Corners: 2px (chips, badges, index items), 4px (buttons, inputs), 6px (cards, dialogs). No pills except status dots.
- Borders: 1px Hairline on cards, inputs at rest, tables; 1px Ink-soft on inputs at focus + focus ring.
- Signature: 3px Seal-Red left rule marks the single active/selected thing (active nav item, open question row, current processing row). Catalog-card silhouette: hairline frame, serif title, mono ledger line, rule, action row.

## Components

### Buttons
Archival stamps: 4px radius, 10px 18px padding, Label voice, min-height 44px. Primary is Seal Red on Paper; Secondary is Paper with 1px Hairline border and Ink text; Danger is text-button requiring checkbox confirm first.
- **Hover / Focus:** primary deepens to Seal Red Deep + 1px lift (ambient-low); every variant shows the focus ring. No scale transforms.
- **Tertiary:** text-only (`Download`, `Open`, `Back to library`) with underline on hover, used inside cards and ledgers.

### Chips
Provenance and type tags: 2px radius, Paper Deep fill, Ink text, 2px 8px padding, Mono 12px. Selected topic = Pine-tinted fill with Pine text; auto-tagged appends `(auto)` in Ink Soft. Never color-only: every dot carries its text label.

### Cards / Containers
Library card and reading pane: 6px radius, Paper ground, 1px Hairline border, 16px padding, flat at rest. Hover lifts to ambient-low. Internal rhythm: title / mono meta / chips / source rows / action row, divided by hairlines.

### Inputs / Fields
Paper ground, 1px Hairline stroke, 4px radius, 10px 12px padding. Focus: Paper Deep fill + Seal focus ring. Error: Ochre/Pine text adjacent + `role="alert"` semantics, never color alone. Sliders carry `help=` units; selects carry paper-scoped help.

### Navigation
Left rail: Label voice, 10px 14px rows, 2px radius, min-height 44px. Rest: Ink-soft text on Paper. Hover: Paper Deep. Active: Paper Deep + 3px Seal left rule (the brief's earned active-marker; the only above-1px edge in the system) + Ink semibold. Mobile: rail becomes a horizontal top bar with the same active rule on the bottom edge. Footer holds the Student/Archivist view switch with its `Editing tools are hidden/visible` caption. No eyebrow kicker sits above any heading: headings carry their own weight.
**Access:** Archive renders for everyone; Tagging Inbox, Syllabus Map, Intake and Pipeline, and Usage Ledger render only for admin sessions. Students get the locked line instead of dead buttons.

### Status ledger
The 4-cell done/queued/running/failed strip and Background-jobs list: Mono numbers, Label eyebrows, hairline dividers. Running rows pulse via opacity (respects `prefers-reduced-motion`: static `Running...` text, no animation). Replaces the former emoji counters.

### Signature Component
**Reading-desk header:** serif Display paper title, mono ledger line (`Paper #42 - JEE Advanced 2023 - 28 questions`), type chips, provenance caption (`vector - assisted crop`), and the 65-75ch reading pane. This composition is the product's face; every other surface defers to it.

## Do's and Don'ts

### Do:
- **Do** keep serif to titles and questions; run every action, count, and path in system/mono.
- **Do** use Seal Red once per region; let hairlines and tone do the rest.
- **Do** pair every toast with inline `st.success`/`st.info` for critical confirmations.
- **Do** name every icon/text-button with `help=` (e.g. `help="Download paper42_full.pdf"`).
- **Do** cap figures at 400px wide with a text provenance caption, never a color dot alone.

### Don't:
- **Don't** ship emoji as UI (no `📖` nav, no `⬇`/`🗑` buttons, no `✅⏳` ledger) - use words and ledger numbers.
- **Don't** use `!important` overrides or Streamlit internal `[data-testid]` selectors in custom CSS.
- **Don't** invent a second accent for buttons; Pine and Ochre are ledger-only.
- **Don't** exceed 75ch in the reading pane or render the full question index past 40 items without collapsing to a select.
- **Don't** add resting shadows, pills, gradients, or glass where the system specifies flat hairline cards.
