# EJEE source inventory and support status

Snapshot of `C:/EJEE-data/ejee.db` (read-only) taken 2026-11-22. Counts are
question items (a grouped question with its continuation pages counts once).
"With solution" = a mapped worked-solution image exists; "key only" = only an
answer key (in the card or the `answer` field); "question only" = neither.
Regenerate: `importer.py plan --config books.json` (catalog) and
`runs/books/source_classification.json` (classification below).

No source from **Narayana** exists in EJEE (titles, tags, original file
names and source paths were searched).

## 1. Textbooks and problem books (olympiads excluded)

About 35-40 physical books, stored as 260+ EJEE sources (Sardana, SBT and
Physics Galaxy are split into chapter/exercise sections).

| Book / series | Questions | With solution | Key only | Question only |
|---|---:|---:|---:|---:|
| Sardana (7 books, 78 sections) | 12,097 | 11,458 | 639 | 0 |
| S.B. Tiwari / SBT (Mechanics, V1, Electricity, Magnetism, SBT-2) | 6,120 | 4,099 | 1,736 | 285 |
| University Physics (Young & Freedman) 15e | 5,635 | 4,496 | 1 | 1,138 |
| Physics Galaxy problem sets | 2,674 | 0 | 2,546 | 128 |
| Anurag Mishra JEE Advanced & Olympiad | 2,327 | 0 | 2,327 | 0 |
| Savchenko, Problems in Physics | 2,023 | 396 | 0 | 1,627 |
| Meriam & Kraige Dynamics 7e | 1,494 | 532 | 32 | 930 |
| Hibbeler Dynamics 14e | 1,351 | 753 | 200 | 398 |
| Hibbeler Fluid Mechanics 2e | 1,276 | 64 | 461 | 751 |
| Irodov, Problems in General Physics | 1,141 | 737 | 281 | 123 |
| Pathfinder | 1,130 | 1,129 | 0 | 1 |
| Morin, Classical Mechanics | 635 | 256 | 0 | 379 |
| Jitender Singh (4 solved-problem books) | 628 | 628 | 0 | 0 |
| Purcell & Morin, Electricity and Magnetism | 592 | 219 | 0 | 373 |
| Kalda (5 booklets) | 369 | 358 | 0 | 11 |
| Other (EM Waves doc, Diffraction doc) | 43 | 42 | 0 | 1 |
| **Total** | **39,535** | **25,167** | **8,223** | **6,145** |

## 2. Material from coaching institutes

### 2a. Institute test papers

| Institute | Questions | With solution | Contents |
|---|---:|---:|---|
| Sri Chaitanya | 7,024 | 5,836 | GTA, PTA, UTA, WTA, GTM (Super60, Jr.XL) |
| Allen (ALLEN + ALLEN NEW) | 6,194 | 5,176 | SRGBT, Advanced/Main tests, GTA, full and part tests |
| FIITJEE | 2,104 | 2,070 | AITS 2023-2025, AIITS, Ai2TS |
| Single Sri Chaitanya GTM paper (`...Q.PAPER`) | 3 | 0 | one Super60 GTM paper |
| **Total** | **15,325** | **13,082** | |

### 2b. Institute study material compiled from papers

| Source | Questions | With solution | Key only | Status |
|---|---:|---:|---:|---|
| BIIT chapter sheets | 6,831 | 0 | 6,712 | supported |
| Allen study material (Revision Assignment 2024: 2,630; JEE Adv modules: 1,723; JEE Main modules: 1,077; Guided Revision 2026: 680) | 6,110 | 2,997 | 3,113 | converted live via the app (§4a, P506) |
| JEE Digital / Jeenious modules | 3,879 | 3,879 | 0 | supported |
| INSP sheets | 2,697 | 0 | 2,697 | supported |
| Unbranded chapter sheets (4A-4E, 5A-5C, 25A-26C) | 595 | 442 | 153 | supported |
| Aakash Book Crunch (6 volumes) | 462 | 334 | 0 | supported |
| **Total** | **20,574** | **11,652** | | |

### 2c. JEE past-year compilation (official exams, not an institute)

| Source | Questions | With solution |
|---|---:|---:|
| PYQ+ (JEE Main/Advanced 1978-2025, chapter-wise, 80 sections) | 6,410 | 6,409 |

## 3. Ignored

| Category | Questions |
|---|---:|
| Olympiad archives (IPhO, APhO, All-Russian, Moscow, MIPT, BPhO, NBPhO, USAPhO, EuPhO, INPhO, IOQP, AAPT F=ma) | 2,755 |
| Actual exam papers (JEE Advanced 2021 P1/P2) | 38 |
| Teaching material, not questions (Indian framed slides, Laws of motion slides, Ambarish chapter-note PDFs) | 4,611 cards |

Olympiad archives are planned and runnable like any book (APhO was in the
pilot); they are only left out of the totals above.

## 4. Conversion cost (measured, not estimated)

Source: `runs/measured-costs.json` (token_usage from each converted part's
own run DB). Pricing from config.yaml: input $0.10/M, cached input
$0.002/M, output $0.20/M. INR at ₹92.89 per USD (22 Nov 2026); "incl. GST" adds
18% Indian GST on imported online services. `run_book.py` prints the same
three numbers per part (rate overridable with env `USD_INR`). "Calls" = model calls; roughly half of each run's
cost is the second pass (topic tagging, ~15 calls), which prompt caching
keeps cheap.

### 4a. Measured parts (submit_pair, preview pruning, edge gate, measured options)

| Part (15 q) | Content type | Extractor (calls) | Topics (calls) | USD total | USD / q | INR total | INR incl. 18% GST | INR / q incl. GST |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BIIT P1 | key-only cards, 1 fig | 20 | 15 | 0.0158 | **0.0011** | ₹1.47 | ₹1.73 | ₹0.12 |
| INSP P1 | key-only cards, 5 figs | — | — | 0.0188 | **0.0013** | ₹1.75 | ₹2.06 | ₹0.14 |
| Galaxy Kin P1 | key-only cards | 18 | 15 | 0.0232 | 0.0015 | ₹2.16 | ₹2.54 | ₹0.17 |
| Hibbeler P1 | printed + handwritten solutions | 31 | 15 | 0.0245 | 0.0016 | ₹2.28 | ₹2.69 | ₹0.18 |
| Meriam Dyn P1 | printed, few figures | 27 | 30 | 0.0301 | 0.0020 | ₹2.80 | ₹3.30 | ₹0.22 |
| SBT Mech P1 | printed + handwritten solutions | — | — | 0.0374 | 0.0025 | ₹3.47 | ₹4.10 | ₹0.27 |
| JEE Digital Kin P1 | printed modules + PYQ exercises | — | — | 0.0353 | 0.0024 | ₹3.28 | ₹3.87 | ₹0.26 |
| Sardana Ch4 P1 | printed, many figures | — | — | 0.0410 | 0.0027 | ₹3.81 | ₹4.49 | ₹0.30 |
| PYQ+ E&M Ch1 P1 | printed, many figures | 48 | 15 | 0.0481 | 0.0032 | ₹4.47 | ₹5.27 | ₹0.35 |
| Young & Freedman P3 | printed, many figures | 56 | 15 | 0.0472 | 0.0031 | ₹4.38 | ₹5.17 | ₹0.34 |
| Irodov P1 | handwritten notes, dense | 123 | 15 | 0.0755 | 0.0050 | ₹7.01 | ₹8.28 | ₹0.55 |
| Aakash BC1 P1 | dense printed modules | — | — | 0.0785 | 0.0052 | ₹7.29 | ₹8.60 | ₹0.57 |
| APhO P1 | olympiad, photos, multi-page (3 figs/Q) | 245 | 15 | 0.2152 | 0.0143 | ₹19.99 | ₹23.59 | ₹1.57 |
| ALLEN test paper P187 | institute test paper via app, direct publish (allowed +3 more) | auto-approved holds | — | 0.0750 | 0.0050 | ₹6.97 | ₹8.22 | ₹0.55 |
| ALLEN test paper P187 | institute test paper via app, direct publish | auto-approved holds | — | 0.0750 | 0.0050 | ₹6.97 | ₹8.22 | ₹0.55 |
| ALLEN revision module P506 | institute study material via app, direct publish | auto-approved holds | — | 0.0514 | 0.0034 | ₹4.77 | ₹5.64 | ₹0.38 |
| Sri Chaitanya GTA P1 | institute test paper via app, direct publish | auto-approved holds | — | 0.0627 | 0.0042 | ₹5.82 | ₹6.87 | ₹0.46 |
| FIITJEE AITS 2025 P1 | institute test paper via app, direct publish | auto-approved holds | — | 0.0538 | 0.0036 | ₹5.00 | ₹5.90 | ₹0.39 |
| JEE Advanced 2021 Paper 1 P1 | actual exam paper via app, direct publish | auto-approved holds | — | 0.0814 | 0.0054 | ₹7.56 | ₹8.92 | ₹0.59 |

### 4a-2. Cache A/B: append-only history (current default)

Pruning old crop previews rewrote earlier messages, so the provider cache
was invalidated from that point on every re-crop. Across the 12 pilots
above, about half the extraction money ($0.31 of $0.61) went on input that
had been sent before but was not served from cache. Pruning is now opt-in
(`prune_previews: true`); the default keeps history append-only. Same part,
same prompt, re-run once:

| Aakash BC1 P1 | Extractor calls | Crop calls | Extractor cached | Extractor USD | Topics cached | Topics USD | USD total | INR total | INR incl. 18% GST | Held figs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pruning (old) | 119 | 108 | 64% | 0.0747 | 96% | 0.0038 | 0.0785 | ₹7.29 | ₹8.60 | 4 |
| append-only + per-edge options | 109 | 93 | 73% | 0.0729 | 57% | 0.0108 | 0.0837 | ₹7.77 | ₹9.17 | 5 |

Cache fallbacks to the bare system prompt fell from 22 to 1, and wasted
cache misses fell from $0.038 to $0.024. Prompts grew 25% because old previews
stay (cached), so extraction is only **~2% cheaper**. The total rose because
the unchanged topics phase happened to get a bad cache day (96% -> 57%):
provider variance, not this change. Net: a small saving, not the 10-20%
first estimated, so the projections in 4b are unchanged. All held figures in
both runs were fixed with `repair` at zero cost.

Rules of thumb: figures drive cost, not text. Key-only/printed books stay at
$0.001-0.003/q. Handwritten notes ~$0.005/q. Photo olympiad problems with
3+ figures ~$0.01-0.015/q. Cache hit rates 40-65% hold input-token cost down;
topic tagging adds only $0.0001-0.0006/q. In rupees incl. GST per question:
printed books ₹0.11-₹0.33, handwritten ~₹0.55, photo olympiads ₹1.10-₹1.64.

### 4b. Expected cost per group (pilot rate of the closest content type applied)

| Group | Questions | Closest pilot | USD / q | Expected cost | Expected INR | INR incl. 18% GST |
|---|---:|---|---|---:|---:|---:|
| Sardana (7 books, 78 sections) | 12,097 | Sardana measured (0.0027) | 0.0027 | **~$33** | ₹3,034 | ₹3,580 |
| SBT / S.B. Tiwari | 6,120 | SBT measured (0.0025) | 0.0025 | **~$15** | ₹1,421 | ₹1,677 |
| University Physics (Y&F) 15e | 5,635 | Y&F measured (0.0031) | 0.0031 | **~$17** | ₹1,623 | ₹1,915 |
| Physics Galaxy sets | 2,674 | Galaxy measured (0.0015) | 0.0015 | **~$4** | ₹373 | ₹440 |
| Anurag Mishra | 2,327 | Hibbeler (0.0016) | 0.0016 | **~$4** | ₹346 | ₹408 |
| Savchenko | 2,023 | Irodov handwritten (0.0050) | 0.0050 | **~$10** | ₹940 | ₹1,109 |
| Meriam & Kraige Dynamics 7e | 1,494 | Meriam measured (0.0020) | 0.0020 | **~$3** | ₹278 | ₹328 |
| Hibbeler Dynamics 14e | 1,351 | Hibbeler measured (0.0016) | 0.0016 | **~$2** | ₹201 | ₹237 |
| Hibbeler Fluid Mechanics 2e | 1,276 | Y&F many-fig (0.0031) | 0.0031 | **~$4** | ₹367 | ₹434 |
| Irodov | 1,141 | Irodov measured (0.0050) | 0.0050 | **~$6** | ₹530 | ₹625 |
| Pathfinder | 1,130 | Hibbeler (0.0016) | 0.0016 | **~$2** | ₹168 | ₹198 |
| Morin | 635 | Hibbeler (0.0016) | 0.0016 | **~$1** | ₹94 | ₹111 |
| Jitender Singh (4 books) | 628 | Meriam (0.0020) | 0.0020 | **~$1** | ₹117 | ₹138 |
| Purcell & Morin E&M | 592 | Irodov handwritten (0.0050) | 0.0050 | **~$3** | ₹275 | ₹324 |
| Kalda (5 booklets) | 369 | Meriam (0.0020) | 0.0020 | **<$1** | ₹69 | ₹81 |
| Other textbook docs | 43 | Meriam (0.0020) | 0.0020 | **<$1** | ₹8 | ₹9 |
| **Textbooks total** | **39,535** |  |  | **~$106** | **₹9,842** | **₹11,614** |
| BIIT sheets | 6,831 | BIIT measured (0.0011) | 0.0011 | **~$8** | ₹698 | ₹824 |
| Allen study material | 6,110 | ALLEN revision measured (0.0034) | 0.0034 | **~$21** | ₹1,928 | ₹2,275 |
| JEE Digital / Jeenious | 3,879 | JEE Digital measured (0.0024) | 0.0024 | **~$9** | ₹865 | ₹1,020 |
| Institute test papers | 15,325 | ALLEN test-paper rate applied (0.0050) | 0.0050 | **~$77** | ₹7,119 | ₹8,401 |
| INSP sheets | 2,697 | INSP measured (0.0013) | 0.0013 | **~$4** | ₹326 | ₹384 |
| Unbranded chapter sheets | 595 | BIIT key-only (0.0011) | 0.0011 | **<$1** | ₹61 | ₹72 |
| Aakash Book Crunch | 462 | Aakash measured (0.0052) | 0.0052 | **~$2** | ₹223 | ₹263 |
| PYQ+ (official past papers) | 6,410 | PYQ+ measured (0.0032) | 0.0032 | **~$21** | ₹1,905 | ₹2,248 |
| JEE Advanced actual papers | 38 | JEE Adv 2021 measured (0.0054) | 0.0054 | **<$1** | ₹19 | ₹23 |
| Institute test papers | 15,325 | ALLEN test measured (0.0050) | 0.0050 | **~$77** | ₹7,119 | ₹8,401 |
| **Grand total, convertible (everything)** | **81,782** |  |  | **~$249** | **₹23,100** | **₹27,257** |

Session spend so far (all pilots, retries, benchmarks, cache A/B): **≈ $1.68 = ₹156.06 (₹184.15 incl. GST)**
(token_usage summed over `runs/*/paperlab.db` + `runs/books/*/part-*/paperlab.db`).

## 5. Support status

### What is supported (any planned source)

- Grouped question + multi-page solution items, standalone key-only cards,
  question-only items (`no_solution_found`), mixed books (grouped + cards,
  e.g. Irodov/SBTV1), split olympiad problems `(part k/m)` (merged into one
  question), passage questions (EJEE repeats the passage on every card, so
  each card is self-contained), sub-part questions (`par-*` qtypes), and
  every native qtype including `nni`.
- Planning: 366 books -> 63,095 questions in 4,388 parts of 15;
  119,267 source images decoded with 0 failures.
- 19 items are blocked before any AI call, each with a recorded reason
  (9 missing image files, 8 invalid body boxes, 2 solution rows without a
  question). They are listed in each book's `plan.json`.

### Converted and checked live

| Book | Part | Result |
|---|---|---|
| Physics Galaxy Ch1 Kinematics | 1 | 15/15, verified, $0.023 (₹2.14; ₹2.52 incl. GST) |
| Hibbeler Dynamics 14e | 1 | 15/15, verified, $0.025 (₹2.32; ₹2.74 incl. GST) |
| Meriam & Kraige Dynamics 7e | 1 | 15/15, verified (first run, no holds), $0.030 (₹2.79; ₹3.29 incl. GST) |
| Irodov | 1 | 15/15, verified after figure approval, $0.076 (₹7.06; ₹8.33 incl. GST) |
| University Physics (Y&F) | 3 | 15/15, $0.047 (₹4.37; ₹5.15 incl. GST); Q8 blocked (EJEE card missing text + foreign figure) |
| APhO | 1 | 15/15, $0.215 (₹19.97; ₹23.57 incl. GST); Q4, Q6 blocked (EJEE source defects, Q6 user-approved) |
| PYQ+ E&M Ch1 | 1 | 15/15, verified, $0.048 (₹4.46; ₹5.26 incl. GST) (Q3+Q13 user-approved: top-edge margin 0 px, no cut content) |
| BIIT | 1 | 15/15, verified, $0.016 (₹1.49; ₹1.75 incl. GST) (Solution-for heading drift fixed + tested) |
| Sardana Mech I Ch4 | 1 | 15/15, verified, $0.041 (₹3.81; ₹4.49 incl. GST) (Q2/sfig1 user-approved: diagram complete, prose above) |
| SBT Mechanics | 1 | 15/15, verified, $0.037 (₹3.44; ₹4.06 incl. GST) (Q1/sfig2 user-approved; Q12 via classify retry) |
| JEE Digital Kinematics | 1 | 15/15, verified, $0.035 (₹3.25; ₹3.84 incl. GST) (Q15/qfig user-approved: bottom-edge graze, blank beyond; Q12 via classify retry) |
| INSP Sheets | 1 | 15/15, verified, zero holds, $0.019 (₹1.76; ₹2.08 incl. GST) |
| Aakash Book Crunch 1 | 1 | 15/15, verified, $0.084 (₹7.80; ₹9.21 incl. GST) (append-only re-run, see 4a-2; Q5 Q10 Q11 figures fixed with `repair`, Q15 `\eqno` fixed by pack; user-approved). Earlier $0.079 run kept as backup |

### Not supported / not yet proven

1. **CLI exclusions:** `run_book.py` still refuses institute test papers
   (Allen, Sri Chaitanya, FIITJEE, the GTM paper) and actual JEE Advanced
   papers, so those categories remain CLI-unproven outside the app. The
   app now converts every EJEE source (including Allen study material and
   actual exam papers) and proved each of these categories live in §4a;
   the app is the path for them.
2. **Not yet converted live:** Pathfinder, Savchenko, Anurag, Kalda,
   Jitender Singh, Morin, Purcell, Hibbeler Fluid Mech, SBT-2, Thermal/Waves/
   SHM sets, Galaxy (other chapters), unbranded chapter sheets. They share
   the grouped/card/key-only layouts proven above, so they are
   supported-by-construction; convert on demand, no dedicated pilot needed.
3. **EJEE card defects** (missing text, foreign figure fragments, truncated
   lines such as a stray "ore than one correct options)." on a Sardana card)
   are transcribed faithfully and are only caught when they produce
   `[UNREADABLE]`, a mid-sentence start or a crop flag. Other fragments need
   human review; they can only be fixed in EJEE.
4. **Not detectable automatically:** a diagram that is never cropped, or a
   label lying entirely outside a crop. Spot review is still required.

### Structural check of every book

`support_check.py` runs `prepare` (no AI) on Part 1 of every planned book:
source rows, ordering, body crops, PDF canvases, paper registration and the
manifest. **Result (2026-11-22): 366/366 books prepared without error**
(`runs/books/support_check.json`). This proves every planned book can be
fed to extraction; it does not prove extraction quality for the families in
"Not yet converted live" above.

## 6. Books converted by other agents

Books not in EJEE (or converted manually with Codex / Claude Code) go
through `custom_importer/` instead: the agent transcribes and crops, submits
into a temp workspace with PaperLab's native savers, then merges. See
`custom_importer/SKILL.md`.
