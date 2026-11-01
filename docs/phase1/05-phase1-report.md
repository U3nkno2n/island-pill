# Phase 1 · Doc 05 — Phase 1 Completion Report

| Project | Island Pill (provisional name — user decision recorded) |
|---|---|
| Phase | 1 — research, audit, architecture |
| Status | **COMPLETE** (awaiting user approval of the five docs, then stop) |
| Date | 2026-11-01 |

---

## 1. What was delivered in Phase 1

| Deliverable | Where |
|---|---|
| TwoCode research (site, demo video, assets) with Verified/Inferred/Unknown separation | Doc 01 |
| Agent-integration research (OpenCode live-verified; Claude Code and Codex from official docs) + AgentEvents v1 protocol definition | Doc 02 |
| Tech-stack evaluation with **measured** baseline (RAM monitor log analysis) | Doc 03 |
| Product architecture: pillars, feature classification (KEEP/OPTIONAL/DROP), module layout, island + companion state machines, storage, settings schema, phased roadmap | Doc 04 |
| This completion report | Doc 05 |

### Research sources actually consumed (fulfilment of §3 of the original brief)

| Source type | What was inspected |
|---|---|
| TwoCode website | `/` (full HTML + site.js + site.css), `/buy/`, `/download/`, `/contact/`; `/feed/` head-registered but not read |
| Demo media | `robo-demo.mp4` (19.3 s, 579 frames) analysed via contact sheets + targeted full-frame reads of: `{working, permission, done, collapsed}` states |
| Character assets | 6 mood SVGs inspected for style/structure only — never copied |
| Local environment | Toolchain versions (GTK/PyGObject/cairo/Python/OpenCode) verified by running version-probes |
| Existing source | `island_pill.py` (1991 lines, structure + state machine + bridge attachment audited), `island_pill_opencode_bridge.py` (405 lines, full read), `island-pill-notify.js` (301 lines, full read), `monitor_ram.py`, `RAM_MONITOR.md`, `install.sh`, `install-opencode.sh`, uninstall script, `selftest.sh`, `tests/` (35 pytest tests), `PHASE_PLAN.md`, both `.opencode` plugin dirs, `README.md`, `CHANGELOG.md` |

### Evidence-quality bona fides

- No inaccessible demonstration was claimed. No browser-interactive TwoCode session was possible (Windows-only product).
- Doc 01 §1 records this limitation explicitly.
- No invented features; Unknowns are listed, not papered over.
- All reference media remain at `/tmp/opencode/twocode/` and are **not** copied into the project (user decision #2).

---

## 2. Decisions made during Phase 1 (recorded for Phase 2)

| Decision | Value / Reference |
|---|---|
| Product name | **Island Pill** (provisional; final naming is a Phase 2-adjacent user decision, not blocking) |
| TwoCode assets stay in `/tmp/opencode/twocode/` | per user decision #2 |
| Detailed implementation task breakdown | **deferred to Phase 2** (user decision #3) — Doc 04 §8 carries only the high-level roadmap |
| Tech stack | Python 3.12 + GTK3 + cairo + X11 (Doc 03 §2, backed by measured 14.7 MB RSS baseline) |
| Rendering/UI | Distro default toolchain; fully custom cairo rendering; no extra fonts |
| Agent transport | single unix socket + AgentEvents v1; three senders; zero polling anywhere |
| Character | procedural vector character renderer ("Bit" as internal codename until a name is chosen); original artwork only |
| Drop-list | Wi-Fi/BT/downloads/CPU-RAM-temp/battery/notification-eavesdropping all retired (Doc 04 §2) |

---

## 3. Open questions (blockers for specific Phase 2/3 work)

| # | Question | Affects |
|---|---|---|
| Q1 | Do you want me to run the **Claude Code interactive-permission spike** (blocking `PermissionRequest` hook relaying Allow/Deny) as a Phase 3 gate? | Phase 3 scope (Doc 02 §2.2) |
| Q2 | Is the **drop-list permanent**, or should the media (MPRIS) tile and/or the extended system-widget pack re-appear later? | Phase 5 scope (Doc 04 §8) |
| Q3 | Which agents matter **first** at launch? (Doc 02 assumes OpenCode first — it is the one installed and verified on this machine — then Claude Code, then Codex when adopted.) | Phase 3 ordering |
| Q4 | Companion name/identity guidance (currently codename "Bit" in Doc 04 §5). | Phase 4 |

---

## 4. Reference materials requested from the user (Doc 01 §5)

To close remaining geometry/behaviour gaps (all optional — the plan does not require them):

1. Real-1920×1080 screenshots of TwoCode states (idle, permission bar, expanded, settings).
2. A short capture of the hover/open/collapse transition and one poke reaction.
3. A moment with **two agents** running simultaneously, showing how TwoCode deconflicts.

---

## 5. Guardrails observed (verification of "nothing else changed")

- No project plan application source was modified; the only write actions in this phase were
  created via the approved writing step: `docs/phase1/01..05` (five files).
- The `.opencode/` dev folders, node_modules, backups (`island_pill.py.opencode-bridge-backup`),
  checksum files, monitor logs, install scripts, and tests are all untouched.
- No dependency installs, no builds, no git operations.

---

## 6. Handoff contract for Phase 2

On approval of these five docs, Phase 2 begins with: restructure of the module skeleton
per Doc 04 §3, migration of KEEP items, and the Phase 2 roadmap slice — task-by-task
breakdown to be produced **at the start of Phase 2** (per user decision #3), not silently
expanded mid-phase.
