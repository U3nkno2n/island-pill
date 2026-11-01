# Phase 1 · Doc 04 — Product Architecture

| Project | Island Pill (provisional name) |
|---|---|
| Phase | 1 (research only) |
| Status | COMPLETE |
| Date | 2026-11-01 |
| Detailed Phase 2 task breakdown | deferred (per decision: Phase 1 carries architecture + roadmap only) |

A Linux-native, agent-first floating companion: a small island at the top-centre of the
screen that follows the user's AI coding agents — surfacing live activity, approval
requests, waiting states, completions — with an original animated companion character whose
reactions give the product its personality, and with a minimal, customisable widget set
behind an expand interaction.

---

## 1. Product pillars

1. **Agent-first identity** — the core product surface is AI agent activity. TwoCode is the
   canonical experience (verified in Doc 01); we recreate it independently.
2. **Batteries hidden** — the system-widget tray-app identity of the old Pill is retired;
   remaining trace elements are limited to the clock/focus tiles and (optional) media tile.
3. **Attention economics** — permission requests break through; everything else is ambient.
4. **Character personality** — the companion reacts with governed moods; user can poke it;
   assets replaceable; behaviours configurable.
5. **Radical lightness** — event-driven instead of polled; 15 MB-class RSS; no startup
   code path performs network/consumer work it doesn't need.

---

## 2. Feature decisions (existing app evaluated item-by-item)

Legend: **KEEP** / **KEEP-lite** (kept, repurposed) / **OPTIONAL** (deferred, revisit by
user) / **DROP** (retired).

| Existing feature | Verdict | Rationale / destination |
|---|---|---|
| Perf hygiene env (`NO_AT_BRIDGE=1`, `GTK_MODULES=""`, `GDK_GL=disable`) | **KEEP** | Proven, meaningful RSS savings |
| DOCK window shell (frameless RGBA, keep-above, stick, skip-taskbar, `input_shape_combine_region` hover zone) | **KEEP** | Core display shell for the new product |
| Spring width/height animator with "only ticks while animating" | **KEEP** | Becomes the central `geom` module powering all state transitions |
| Hover/click open + pending-peek promotion logic | **KEEP** | Interaction model reuse |
| Unix-socket agent event bridge (`island_pill_opencode_bridge.py`) | **KEEP → expanded** | Foundation of the universal `agents` layer; protocol upgraded (Doc 02) |
| OpenCode plugin (`island-pill-notify.js`, API 1.19.5 verified) | **KEEP → upgraded** | Becomes the model sender template for all agents |
| Peek/banners machinery (`show_peek`, pending queue, peeks-while-quiet) | **KEEP** | Feeds permission bar, confirmations, done/error banners |
| Chime/sound (`play_alarm`) | **KEEP** | TwoCode parity: sound on `done` / `question` / `error`; now configurable |
| Focus timer | **KEEP-lite** | Becomes the widget-grid Focus tile (TwoCode shows `5:00 Focus`) |
| Clock (24 h toggle) | **KEEP-lite** | Widget-grid clock tile |
| Right-click → quit | **KEEP** | Plus a settings menu entry |
| Autostart via `install.sh` (unprivileged, idempotent) | **KEEP** | Same pattern + log under `~/.local/state/island-pill/` |
| `monitor_ram.py` dev harness + `selftest.sh` + 35 headless pytest tests | **KEEP** | Continuous regression guard on RSS and animation/logic |
| MPRIS media card | **OPTIONAL** | TwoCode shows a Spotify tile; trivially reachable using existing code — ship if budget permits (Phase 5) |
| CPU / RAM / temperature readouts | **DROP** | Out of new product scope |
| Wi-Fi / Bluetooth widgets, peeks, toggles (incl. all BlueZ/NM wiring) | **DROP** | System-tray app identity retired; may return as an optional extended-widget pack later |
| Download detection (0.5 s net polling, partial-file scanner, indeterminate bars) | **DROP** | The only real poller removed; idle CPU dropped further |
| Battery / charge-flash / low-battery warnings | **DROP** | Same reason |
| `org.freedesktop.Notifications` eavesdropping (BecomeMonitor) | **DROP** | Replaced direction: **send** libnotify desktop notifications instead of siphoning unrelated ones |

**New features** this build introduces: agent session registry with focus state;
live agent card (status sentence, diff/last-action preview, step counter); permission
Allow/Deny bar with confirmation feedback ("allowed, continuing…"); local capped history
feed; companion character (procedural form + mood machine, poke interactions, theme
colours); settings popover (see §7); chime + libnotify sends; multi-agent future-proofing.

---

## 3. Module architecture (target layout)

```
~/.local/share/island-pill/                # deploy target (current pattern)
  island_wire.py            # GtkWindow shell: DOCK hint, RGBA visual, X11 shapes, placement
  anim.py                   # spring animator — only ticks while state differs
  theme.py                  # colour tokens, cached glow masks, colour settings
  protocol.py               # AgentEvents v1: parse/validate/dedup (pure, unit-testable)
  agents.py                 # unix-socket server + session registry (wake state machine)
  history.py                # capped in-memory feed + history.jsonl persistence
  island_render.py          # painters: compact, permission, peek, expanded
  companion.py              # mood state machine + procedural cairo character
  widgets.py                # clock tile, focus timer tile, optional media tile
  notify.py                 # chime (existing play_alarm path) + org.freedesktop.Notifications send
  settings.py               # ~/.config/island-pill/config.json + settings popover
  main.py                   # single-instance guard, wiring, GLib main loop

agents_senders/            # helper senders installed by installer (one file each)
  claude-send.py            # Claude Code hooks bridge (stdin JSON → socket)
  claude-permission.py      # blocking PermissionRequest relay (Phase 3 spike)
  codex-notify.py           # Codex notify → socket
  island-pill-notify.js     # upgraded OpenCode plugin → ~/.config/opencode/plugins/
```

Layers: `island_wire` (I/O, GTK, X11) never contains business logic;
`protocol/agents/history/companion` contain no GTK imports and are fully headless-testable,
following the existing test-suite's structural patterns (`tests/test_island.py` style).

---

## 4. Island state machine

```
                 ┌────── auto, after peek timeout ──────┐
                 ▼                                     │
  hidden ─ agent event ─ compact ─ done/error/info ──── peek bar ──► back to compact
    │               │
    │               ├─ permission/question ─ permission bar ─ answer ─ confirmation flash ─► compact
    │               │
    ▲ hover/click   │ any state
    ├──── expanded ◄┘  (agent card + tiles, collapses on leave/close)
    │
    └─ no agent activity, nothing quietly ──► hidden (invisible hover zone stays)
```

Compact register (a top-centre station):

| Register | Trigger | Content |
|---|---|---|
| `hidden` | 0 agent activity, no peek, nothing to say | invisible 8 px hover zone (existing mechanism) |
| `blob` | agent `started`/`idle` | collapsed blob + companion head |
| `bar_working` | agent `working` | thin bar + orange accent + progress/dot |
| `bar_permission` | agent `permission`/`question` | full-width-ish bar: warning dot, question text, **Allow / Deny** pills, companion |
| `bar_info` | agent `done`/`error`/`status` | accent green/red + title + summary + companion |
| `expanded` | hover/click from any state | agent card + history strip + widget tiles |

Transitions use the spring animator; only window geometry/contents/glow refresh on
state changes — no scheduled frame loop otherwise. Permission bar, once answered:
a confirmation flash (`Allowed, continuing…` / `Denied by you`) for ~2 s, then relax.

Multi-session policy (inferred-draft, needs user input): only one bar at a time;
permission beats question beats working; most recent first within equal priority; full
session list lives inside `expanded`.

---

## 5. Companion state machine (mood engine)

Mapping (all verified/derived in Doc 01):

| Agent event/state | Companion mood | Eyes/shape | Accent | Sound |
|---|---|---|---|---|
| idle (long) | `sleepy` | half-lidded + Zzz | blue-grey | none |
| `started`/`working` | `focused` | narrow eyes | amber | none |
| `working` (ext.) | `curious` | oval eyes | teal-green | none |
| `permission`/`question` | `curious` | oval eyes + antenna wiggle | orange | soft chime |
| `done` | `happy` | ^^ green | green | chime + libnotify |
| `error` | `dizzy`→ `concerned` | X / droop | red | error blip |
| poke (single) | `wink` | one eye closes | — | pop |
| poke (too many) | `dizzy` | spiral eyes | warm | groan |
| user customizes | `in-love` (heartbeat after task done) | hearts | pink | — |

Character stays **procedural** (rounded-rect head, visor with brow line, glowing eyes,
antenna, side pods, soft shadow — original geometry, not traced from TwoCode assets).
Breathing/blink scheduled with randomised, generously-spaced timers (idle CPU zero between
events). Mood persistence is per-session, reset on agent silence.

---

## 6. Data, storage, and desktop integration

| Data | Path | Notes |
|---|---|---|
| config | `~/.config/island-pill/config.json` | see §7 |
| history feed | `~/.config/island-pill/history.jsonl` (capped ring, e.g. 200 entries) | bounded size |
| log | `~/.local/state/island-pill/island-pill.log` | current pattern kept |
| agent session runtime memory | in-process only | restarting loses transient session states by design |
| sender plugin (OpenCode) | `~/.config/opencode/plugins/island-pill-notify.js` | current pattern kept |

Desktop deliverables (all user-level, no root):
- autostart `.desktop` in `~/.config/autostart/`;
- libnotify desktop notifications on permission/done/error (action buttons: reveal island);
- chime via existing sound path;
- per-agent toggle integration settings installer (Claude hooks / Codex notify config edits
  are made by the installer only when the corresponding agent has been detected and opted in —
  no ~/dots-file junk dropped silently).

---

## 7. Settings schema (draft)

```json
{
  "clock24": false,
  "agents": { "opencode": true, "claude": true, "codex": true },
  "claude_interactive_permissions": true,
  "sound": { "enabled": true, "volume": 0.6 },
  "desktop_notifications": { "done": true, "permission": true, "error": true },
  "companion": { "enabled": true, "poke_dizzy": true, "name": "Bit" },
  "animation": "full | reduced | minimal",
  "theme": { "bg": "dark-warm", "focus_colour": "#e8b884", "done_colour": "#39d97a" },
  "history_entries": 200,
  "debug_log": false
}
```

Settings UI: a small popover (gear icon in the expanded panel's top-right) — TwoCode-parity
"Colours, sound" section names first.

---

## 8. Roadmap (high-level only; task breakdown lives in Phase 2)

| Phase | Goal |
|---|---|
| **Phase 2** | Core island restructure: window/anim/render skeleton from KEEP-items;
compact/expanded registers, clock + focus tiles, settings file + popover, installers refresh,
test-suite extension. Shell/UI only — no agents wired yet. |
| **Phase 3** | Agent layer: protocol module, socket server, session registry, upgraded
OpenCode sender, agent card (status/detail/progress), permission bar + Allow/Deny with
confirmation + chime + libnotify, history feed. Gate: Claude PermissionRequest live spike
(Doc 02 R1) before exposing that path. |
| **Phase 4** | Companion character (procedural renderer, moods, blink/breathing, poke
reactions), theme polish (accents, glow, rounding), animation tuning, RAM/CPU confirmation
runs versus Doc 03 budget, README rewrite. |
| **Phase 5** | OPTIONAL items: MPRIS media tile, Codex rollout tailer if no notify
sufficiency, drag-companion "ask about my screen" experiment (needs a screenshot helper
decided separately), extended widget pack (Wi-Fi/BT) only if user re-prioritises. |

---

## 9. Testing strategy (inherited + extended)

| Layer | Approach |
|---|---|
| protocol / registry / moods / geom | pure-python headless unit tests (extend existing pytest suite patterns; 35 tests carry over) |
| window/shapes | no-interactive display available → logic-level tests only; live X11 behaviour verified manually with selftest checklist |
| installers | same idempotency tests (existing `selftest.sh` harness extended to new paths) |
| perf | monitor_ram runs at phase gates (existing harness) — Doc 03 budgets as pass/fail |
