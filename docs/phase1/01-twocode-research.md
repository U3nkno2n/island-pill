# Phase 1 · Doc 01 — TwoCode Research

| Project | Island Pill (provisional name — final name TBD) |
|---|---|
| Reference product | TwoCode (https://twocode.nl/) — "A little island for your AI" |
| Phase | 1 (research only) |
| Status | COMPLETE |
| Date | 2026-11-01 |
| Reference assets | `/tmp/opencode/twocode/` — kept OUTSIDE the project; never copied into the application |

TwoCode is the primary design and functional reference for the new Island Pill. This document
records everything that could be established from the publicly accessible website and the
promotional demo video, separated into **Verified / Inferred / Unknown**, followed by the
design implications for our independent re-implementation. No proprietary source code or
artwork was copied.

---

## 1. Evidence sources inspected

| # | Source | What it is | Outcome |
|---|---|---|---|
| 1 | `https://twocode.nl/` | Landing page full HTML (~66 KB), plus its `site.js` and `site.css` | Fully analysed |
| 2 | `https://twocode.nl/buy/` | Purchasing page | Redirects to Stripe Checkout; no further product info |
| 3 | `https://twocode.nl/download/` | Download page | Install flow + self-update statements captured |
| 4 | `https://twocode.nl/contact/` | Contact page | Email-only contact, beta framing |
| 5 | `https://twocode.nl/feed/` | RSS | Listed in `<head>`, not inspected (not product-relevant) |
| 6 | `robo-demo.mp4` (19.3 s, 720×900, 579 frames) | Officially linked demo video | Downloaded to `/tmp/opencode/twocode/robo-demo.mp4`; inspected via contact sheets (1 fps, 2 fps, 4 fps) and 3 targeted full-frame reads |
| 7 | `robo-demo.jpg` (poster) + 6 Robo mood SVGs (`focus, curious, happy, wink, heart, dizzy`) | Character assets linked from the page | Downloaded and inspected for style/structure research only |

Interactive browser sessions (running the application, hovering the island, seeing it live on
Windows) were **not possible** — TwoCode is a Windows-only product and there is no web-embeddable
version of it. All interactive-state evidence below therefore comes from the page copy and from
frame-by-frame analysis of the official demo video.

---

## 2. VERIFIED findings

Directly observed in the website HTML/copy or in the demo video frames.

### 2.1 Product definition & pricing

| Finding | Evidence |
|---|---|
| "A Dynamic Island for Windows." — Windows 10 and 11 only. FAQ explicitly: "This download is for Windows 10 and Windows 11. It is not a macOS app." | Homepage meta description, JSON-LD, FAQ |
| No Linux build exists or is mentioned anywhere on the site ("Linux" appears 0 times). Our port is an original product proposition. | Full-text scan of page |
| €9.99 once — no subscription, "yours forever, on up to 3 PCs, with every update". Free-beta users stay free forever ("Founder" cohort). | Pricing appears in 7 places (hero badge, hero note, CTAs, FAQ, footer, JSON-LD) |
| Install: ZIP → extract → run `TwoCode.exe`. Island appears at the top of your screen. Setup.exe flow says: "Robo appears at the top of your screen. That's it. TwoCode updates itself from then on." | `/download/`, How-it-works step 1 |
| One-person product; unsigned build (Windows SmartScreen "unknown publisher" explainer), self-updating after install. | `/download/` |
| Monitoring agents: Claude Code and Codex only, in the current public beta. Toggled per-agent in **Settings → AI**. "Restart the agent once to finish connecting." | FAQ, Features §4, How-it-works step 2 |
| Agent identity is separate: "Your existing AI account or subscription is separate from TwoCode." | FAQ |
| Data posture: "TwoCode reads the status of Claude Code and Codex **locally** on your PC." Sending content to the AI happens only for the "Ask Robo" screen-question flow (question + screenshot). | FAQ "Where does my data go?" |
| Completion UX: "A sound, a colour and a Windows notification tell you when your AI finishes or needs a decision." | Benefit 03 |
| OpenCode / Cursor / Windsurf / Copilot / Gemini / MPRIS: never mentioned on the site. | Full-text scan |

### 2.2 Island states (demo video frames)

| State | Verified appearance |
|---|---|
| **Idle / collapsed** | Small dark blob hanging from the top edge of the screen, horizontally centred; contains only Robo's head. Two visual variants observed: a small rounded notch-bar and a slightly larger organic blob (both vertically attached to the screen edge). |
| **Collapsed + glow (tray-form)** | Same blob, but circled by a **soft orange glow ring** while the agent is working; turns **cyan/white** when the agent settles (e.g. after "Done"). |
| **Working (compact pill)** | A wider, very thin bar at top-centre: a thin amber/orange progress element with a small green badge/dot on the right edge. Appears while an agent is mid-task. |
| **Permission request** | A wide bar (~45–50 % of frame width) at top-centre: left = orange warning dot + text `Allow: git push origin main?`; middle = a solid green **Allow** pill button next to a muted **Deny** pill button; right = Robo icon. |
| **Post-decision confirmation** | A confirmation bar reading `Claude · Allowed, continuing…` before the UI relaxes back. |
| **Success** | A bar/panel reading `Claude · Done` with a **green accent**, body text like `Stripe checkout is live. 48 tests pass…`. |
| **Expanded panel** | Wide dark rounded panel (≈ 80–85 % of frame width in the mock screen) with: a top icon row (home + history icons on the left; sound, settings, help icons on the right); a large **agent card** on the left; and a **2×2 widget grid** on the right. |
| **Agent card (expanded)** | Circular Robo avatar at far left; status dot + project name (`webshop`) + agent label (`Claude Code`); second line = status sentence (`editing checkout.ts`, `Claude is working`, `Done`); top-right of card = step counter `1/2` → `2/2`; card body shows a **code diff preview** (red removed line `- const total = 0`, green added line `+ const total = sum([])`) or a completion message. |
| **Widget grid (expanded)** | Four tiles, each a coloured rounded-square icon + title + subtitle: **Spotify · Music**, **5:00 · Focus**, **clock · 14:36 Mon 12 Oct**, **Settings · "Colours, sound"**. |
| **Accent language** | Orange/amber = working or permission-warning; **green** = success/settled. The expanded panel's outer glow follows the same mapping. |

### 2.3 Robo character (mascot)

| Attribute | Verified detail |
|---|---|
| Build | White/off-white rounded-oval "head plate"; a black rounded-rectangular **visor** across the face with a thin grey "brow" line at its top; **two glowing eyes** rendered inside the visor; a thin **antenna** from the top of the head ending in a small white ball; rounded rectangular **side pods** ("ears") on both sides of the head; the character **floats** above a soft elliptical **shadow**. |
| Proportions | Roughly round head, viewBox 200×190 in the SVG assets; eyes sit low in the visor; the character head is displayed inside dark "island" chrome tiles in the video. |
| Moods (site ticker, verbatim quotes) | **Happy** — "The work is done. Robo is here with a little celebration and the result, ready when you are." · **Curious** — "Your AI has a question. Robo makes sure you know when it is your turn to decide." · **Focused** — "Your agent is working. Get on with your own work and let the island keep you in the loop." · **Wink** — "A small companion for your desktop, with a personality of his own." · **In love** — "More than a status icon. Robo brings a little character to your working day." · **Dizzy** — "Go easy on him. Poke Robo too often and he might need a moment to recover." |
| Extra mood (video only) | **Sleepy** — half-lidded eyes with floating `Z Z Z` letters, faint blue-grey tint. |
| Eye expressions seen | Happy: closed upward arcs (^^), green. Curious: solid glowing oval eyes, green. In love: two pink hearts. Sleepy: half-lidded green eyes + Zzz. Focused: visible in video with amber-tint tile. Dizzy: spiral/X eyes (per montage). |
| Mood presentation | A dark **badge pill** under the character in feature cards: coloured dot + mood word ("Happy", "Curious", "In love", "Sleepy", "Focused"). The **card background tints with the mood** (green for Happy, maroon/dark-red for In love, dark for Curious, blue-grey for Sleepy, warm amber for Focused). |
| Art style | The on-site SVGs use hand-drawn "pencil sketch" rendering with SVG `feTurbulence` displacement filters and cross-hatch patterns. Proprietary assets — style reference only, never copied. |
| Interaction | "He blinks, gets curious when your AI has a question, and gets dizzy if you poke him too often." Poke counting → over-poke triggers the Dizzy recovery mood ("Ouch! Too many taps… need a sec" caption observed in the video). |

### 2.4 Feature claims (site copy, verbatim)

1. "See which file Claude Code or Codex reads, what it changes and which command it runs. A small island keeps the important bits in view." — *Your AI, live*
2. "When your AI needs permission, allow or deny the action right in the island. No searching through terminal windows." — *You stay in control*
3. "A sound, a colour and a Windows notification tell you when your AI finishes or needs a decision. Keep working until it does." — *Know when it's done*
4. "Drag Robo onto a window and ask what's going on. He uses the AI you connected to help you understand what's on your screen." — *Ask Robo about your screen*
5. "See activity, progress and the latest answer in one place. TwoCode follows the agents you connect in Settings → AI."
6. "Get a chime and a visible status when your AI finishes or has a question. Open the island to see the result and your **history**."

(the last two confirm a **visible history** surface and that "the latest answer" is displayed in-island)

---

## 3. INFERRED findings

Reasonable interpretation of observed behaviour — not directly confirmed.

- **Geometry at 1080p** (extrapolated from the mock screen in the video, low confidence): expanded island ≈ 1500–1650 px wide, ≈ 220–260 px tall; permission bar ≈ 900 px × ≈ 44 px; collapsed blob ≈ 130–160 px wide, ≈ 34–44 px tall. Real Windows-size screenshots are needed for precision (see §5).
- **Motion:** expand/collapse reads as spring/eased width+height growth (blob → bar → panel), matching the Dynamic Island idiom. Blur/glow appear as soft rounded halo strokes rather than heavy effects.
- **Agent card feed:** the status sentence ("editing checkout.ts", "Claude is working"), the diff preview, and the `1/2` counter are plausibly derived from the agent's live feed — i.e. the same UI is agent-driven rather than hand-animated.
- The **history icon** in the expanded panel's top row opens a recent-events list (copy mentions "your history").
- The **widget grid is customisable** — "Settings · Colours, sound" tile implies the grid is the natural place for ours (sound/toggles).
- The expanded agent card likely opens on **click** of the collapsed island; the permission bar may auto-present as a stuck-compact state because it demands user input.
- "Claude" and "OpenAI" tiles labelled "Robo's chat" in the compatibility section are the two backends for the **drag-Robo-to-ask** flow (question + screenshot → connected AI), matching data-posture FAQ wording.

---

## 4. UNKNOWN findings

Could not be established; must not be assumed in the design.

- Exact pixel geometry / scale behaviour on real Windows displays at 1080p and other resolutions.
- Multi-monitor behaviour; whether the island is per-monitor or primary-only.
- Dwell/hover thresholds, click vs hover semantics for expand/collapse, Escape/keyboard shortcuts.
- Whether the widget grid entries can be removed/reordered by the user.
- Sort/focus rules when **multiple agents and multiple sessions** run concurrently (TwoCode's UI shows one agent card).
- Light-theme support, theming scope ("Colours" settings exist but contents unseen).
- Sound design details (polyphony, volume control, on/off defaults).
- Presence/absence of a system tray icon on Windows.
- Auto-update mechanics, licensing/activation checks, any telemetry.
- Whether "Ask Robo" works with restricted/sandboxed shells, and its exact UX (drag animation, answering surface).

---

## 5. Required reference materials (to firm up remaining gaps)

Send these to close the Inferred/Unknown gaps:

1. Screenshot, real 1920×1080: **idle collapsed island** on plain wallpaper.
2. Screenshot: **permission bar** with Allow/Deny (any agent).
3. Screenshot: **expanded island** with agent card + widget grid.
4. Screenshot: **settings window(s)** — colours, sound, AI toggles.
5. Short (~10 s) capture: hover/open/close transition and one **poke reaction**.
6. Optional: behaviour while **two agents** run simultaneously.

---

## 6. Design implications for Island Pill

1. **Two visual registers** are enough to recreate the experience: a *compact register* (blob/pill/bar for idle/working/permission) and an *expanded register* (panel with agent card + widget grid). A separate overlay for every event is not needed — peek bars reuse the compact register.
2. **Motion is the identity**: springy transitions, tinted accents (orange = working/attention, green = success), and a floating, breathing companion. Prioritise animator quality and frame discipline over larger features.
3. **Character modularity**: companion must be a replaceable panel (procedural vector default; PNG/SVG skin packs later). Original artwork only — no cloned Robo.
4. **Iconography**: status dots, dark low-chromium chrome, small white-on-dark text, coloured squared icon tiles.
5. **Event model**: permission (blocking UI), question/waiting (attention), working (ambient), done (celebration + sound + desktop notification), error (attention). All states must be producible from the agent-event protocol (Doc 02).
6. **History** is a first-class product element — keep a local, capped event feed from day one.
7. Our additions beyond TwoCode (per user direction): Linux-native D-Bus integration opportunities; multi-session handling TwoCode does not demonstrate.
8. **Never copy:** Robo artwork, TwoCode names/strings, or any site asset. Independent rendering of an original character and a legally distinct layout/palette.
