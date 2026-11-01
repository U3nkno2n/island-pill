# Phase 1 · Doc 03 — Technology Stack Evaluation

| Project | Island Pill |
|---|---|
| Phase | 1 (research only) |
| Status | COMPLETE |
| Date | 2026-11-01 |

Constraints (user environment): Linux Mint 22.3 Cinnamon · X11 · AMD Ryzen 5 3550H ·
6 GB RAM · hybrid GTX 1650 / Vega 8 · 1920×1080@60. Targets: **≈ 30–60 MB idle RSS**
(aim significantly lower), near-zero idle CPU, smooth animation, minimal polling,
no heavyweight runtimes (excluded: Electron, any WebView), no added pip dependencies,
no network traffic at runtime.

---

## 1. Measured baseline (evidence, not assumption)

The current application already ships a measurement harness (`monitor_ram.py` +
`RAM_MONITOR.md` + `ram_log.csv`). Relevant settings: ~2-hour continuous capture.

| Metric | Value |
|---|---|
| Idle RSS | **≈ 14.7 MB** (`RSS=14740kB` samples) |
| Idle PSS | **≈ 9.0 MB** (`PSS=9042–9049kB`) |
| Private memory | **≈ 8.5 MB** (`PrivD=8516kB`) |
| Startup transient | ~60 MB RSS for the first sample (interpreter + shared-map warmup), settles immediately |
| Trend | flat (no growth) across the log |

Source: `/home/unkno2n/Downloads/pill/monitor_ram.log` (1219 lines, sampled at 5 s).

**Verdict:** the stack is far below the 30–60 MB target — 4× under budget — before even
dropping the Wi-Fi/Bluetooth/download pollers (Doc 04 classification). Idle CPU is already
"clock-once-a-minute" plus animation-frames-only-while-moving (per source design), and the
new architecture removes the only remaining true poller (the 0.5 s `/proc/net/dev` read in
the downloads detector).

---

## 2. Decision matrix

| # | Option | Verdict | Rationale |
|---|---|---|---|
| 1 | **Python 3.12 + PyGObject (GTK3 3.24.41) + Cairo + X11** — *keep-and-restructure* | **KEEP (chosen)** | Measured 15 MB RSS / near-zero idle CPU on this exact machine. All bits already in the distro (verified: GTK 3.24.41, PyGObject 3.48.2, PyCairo 1.25.1, Python 3.12.3). No extra packages needed. Whole rendering path is hand-drawn cairo on an RGBA visual; GTK is used only as the window/event loop, so no real toolkit overhead is retained (proven by the current app's numbers). Huge reuse of the already-verified `Island` base work (shape/input shape, hover, spring animator, peek, D-Bus, alarm). |
| 2 | Electron / Chromium / WebView (an idea explicitly excluded) | REJECT | 250–450 MB RSS, running a browser engine violates the core requirement; performance target unreachable. |
| 3 | Qt / PySide6 / PyQt6 | REJECT | +35–70 MB RSS minimum, big shared libs, no gain: the island is fully custom-drawn anyway, so the toolkit's widgets/Button styling never actually get used for anything that GTK3 wouldn't. Animation cost identical (still cairo/manual). |
| 4 | tkinter | REJECT | No quality ARGB compositing (per-pixel alpha), no clean X11 input-shape workflow for a hover-zone overlay; dated text metrics. Would force custom drawing into a worse toolkit. |
| 5 | GTK4 (libgtk-4 1.1400.5 available on this system) | REJECT for now | Same custom-drawn model, but: more churn to port, no measurable RSS win expected at this size, no new widget needs. Revisit only if a GTK4 feature hard-requires it. |
| 6 | Rust / Zig / C rewrite (gtk4-rs or raw Xt/Xlib) | DEFER | Would cut baseline further (maybe 8–12 MB) but 5–10× implementation cost for a gain already 4× below target. Revisit only if profiling ever fails. Rapid-iteration value of Python matters for the big UI/companion scope. |
| 7 | SDL2 / raylib / Allegro | REJECT | Would need bespoke text layout, DPI handling, IME, window resizing — no benefit over cairo's mature text via PangoCairo. |
| 8 | Python + custom X11 (ctypes/Xlib, no GTK) | REJECT | The current app already proved GTK3's event loop + X shape combos work well here; raw Xlib means reimplementing timers, cursor geometry, monitor tracking, and repaint scheduling by hand with no measured saving. |

---

## 3. Rendering plan (why cairo is enough)

- **Single cairo painter pipeline.** The island is drawn each frame on an RGBA surface (an
  `ImageSurface` composited onto the window's cairo context, as the current app does — the
  same path TwoCode's equivalent visuals need).
- **Procedural character** — companion is drawn with vector primitives (head/visor/eyes/antenna/
  pods/shadow as simple rounded paths + radial gradients). No image decode in steady state
  (the downloadable SVG "pencil" style is decorative site art, not a requirement in-app).
- **Glow:** soft rounded-rect halos via pre-blurred cached masks (rendered once per accent
  colour per size change), composited cheaply — avoids per-frame `feTurbulence`-like cost.
- **Frame discipline:** animations tick only during transitions (the current app's 30 fps
  "only while a visual transition is active" pattern is kept and made architectural). Idle
  frames do not exist; the companion breathing/blink is timer-scheduled and cheap.
- **Text:** Pango layout (already imported and fast-pathed in the current painter helpers).

---

## 4. X11 specifics (Linux Mint Cinnamon)

| Need | Mechanism (already in use/proven) |
|---|---|
| Always-on-top, all-desktop overlay | `Gtk.Window` with `type_hint=DOCK`, `stick()`, `keep_above`, `skip_taskbar/pager`, no decorations |
| Per-pixel transparency | RGBA visual + `app_paintable`, compositor present on Cinnamon |
| Non-rectangular hit area | `input_shape_combine_region` (XShape) — invisible hover-zone at top edge, expandable to the pill only while it is interactive |
| Click-through outside the island | shape regions cut exactly to the pill surface |
| Monitor placement | `Gdk.Display` monitor geometry, positioned top-centre of primary monitor |
| Future Wayland | out of scope; requires a portal/layer-shell follow-up, noted as risk not blocker |

---

## 5. Runtime budget (design-level)

| Resource | Budget |
|---|---|
| Idle RSS | well under 20 MB (measured 14.7 MB today as the base; removing Wi-Fi/BT/download stack should shave a little; agent registry/history are small in-memory lists + capped JSONL) |
| Idle CPU | 0 % — wake-ups: 1/min clock; GLib io-watch on unix socket (event-driven); animation frames only during transitions |
| Event-time CPU | single JSON line parse + state update + one re-render — milliseconds |
| Disk | bounded: capped `history.jsonl`, config JSON, state log; the only continuously written agent data lives in the agents' own stores |
| Network | zero runtime requests (no telemetry, no version polling) |

---

## 6. Dependency footprint

- Runtime deps: `python3-gi`, `gir1.2-gtk-3.0`, `python3-gi-cairo`, `libglib2.0`, `python3-cairo`
  — all preinstalled on Mint 22.3; zero pip packages; zero vendored JS for the app itself.
- The OpenCode *sender plugin* is a single-file ES module (Bun runtime provided by OpenCode
  itself; its `.opencode/` node_modules exists only because the user develops the plugin — not
  shipped by us).
- Packaging remains a file copy + autostart `.desktop` + versioned installers (current pattern).

---

## 7. Risks

| Risk | Assessment |
|---|---|
| CPython GC latency causing dropped frames during transitions | bounded: render costs are ms-scale; choose exact data structures sizes now (registry dict, deque history) — tested in Phase 4 perf check |
| GTK3 maintenance risk (eventually deprecated upstream) | accepted for this product's size; port-economics documented; the fully-cairo drawing model keeps a GTK4 port a paint-layer swap |
| Wayland future (Mint default may shift) | documented today; layer-shell/deprecation path is a follow-up concern, explicitly out of current scope |
| Copyright issues on visual style | mitigated: independent character, independent layout, no TwoCode assets shipped (Doc 01 §6) |
