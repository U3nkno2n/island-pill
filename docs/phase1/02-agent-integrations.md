# Phase 1 · Doc 02 — AI-Agent Integrations

| Project | Island Pill |
|---|---|
| Phase | 1 (research only) |
| Status | COMPLETE |
| Date | 2026-11-01 |

Design goal: **all senders push; Island Pill polls nothing**. Idle CPU must stay at zero
when agents are quiet; wake-ups happen only on real agent events. This document defines the
transport protocol and investigates how each target agent can be taught to speak it.

---

## 1. Protocol — AgentEvents v1

A single JSON-lines protocol over a unix domain socket, borrowed from the existing
OpenCode bridge's proven architecture (`island_pill_opencode_bridge.py`) and extended to
cover every agent and state.

**Socket:** `$XDG_RUNTIME_DIR/island-pill.sock` (0700 dir, 0600 file, user-owned).
**Framing:** one JSON object per `\n`; server replies `{"ok":true}` (plus optional decision).
**Behaviour:** newline-split receiving, 64 KB max message, 10 s client inactivity timeout,
dedup key `(agent, kind, session, reqid)` with 5 s TTL — all carried over from the existing bridge.

```json
{
  "v": 1,
  "agent": "opencode | claude | codex | <future>",
  "kind": "started | working | permission | question | done | error | idle | status",
  "session": "opaque session/chat id (optional)",
  "project": "project/worktree display name (optional)",
  "title": "short first line, max 200 chars",
  "detail": "longer body, max 500 chars (diff preview, last message, error message)",
  "progress": { "cur": 1, "total": 2 },
  "ts": 1720000000,
  "reqid": "dedup/participation id (optional)"
}
```

State mapping used by Session Registry + Companion (Doc 04):

| Agent source event | `kind` |
|---|---|
| session/chat created | `started` |
| tool runs / streaming parts / rollout growth | `working` |
| permission request | `permission` (interactive: server replies `decision`) |
| agent asks the user a question | `question` |
| turn completed / session idle | `done` |
| turn failed / session error | `error` |
| no agent running (informational) | `idle` |

---

## 2. Per-agent integration research

### 2.1 OpenCode — VERIFIED live in this environment

- Installed: OpenCode **1.19.5** at `~/.opencode/bin/opencode`; config at
  `~/.config/opencode/opencode.jsonc`; plugin dir `~/.config/opencode/plugins/`.
- The existing `island-pill-notify.js` plugin (installed globally by
  `install-opencode.sh` → `~/.config/opencode/plugins/island-pill-notify.js`) already speaks
  to the bridge over the socket and is **verified working** against plugin API 1.19.5
  (documented as `export const server = async ({ project, client, $, directory, worktree })`
  returning a hooks object with an `event: async (input)` hook).

Event list documented at https://opencode.ai/docs/plugins/ (VERIFIED, current site):

| Category | Events available |
|---|---|
| Permission | `permission.asked`, `permission.replied` |
| Session | `session.created`, `session.idle`, `session.status`, `session.error`, `session.updated`, `session.compacted`, `session.diff`, `session.deleted` |
| Message / working | `message.updated`, `message.part.updated`, `message.part.removed`, `message.removed` |
| Tool | `tool.execute.before`, `tool.execute.after` |
| Files | `file.edited`, `file.watcher.updated` |
| Progress | `todo.updated` |
| TUI | `tui.prompt.append`, `tui.command.execute`, `tui.toast.show` |
| Other | `command.executed`, `installation.updated`, `lsp.client.diagnostics`, `lsp.updated`, `server.connected`, `shell.env` |

**Planned sender (upgrade of existing plugin):**

- `session.created` → `started` (project name from worktree/dir basename — pattern proven in the current plugin).
- `message.part.updated` / `tool.execute.*` / `file.edited` → `working` (title = file/tool, throttled).
- `permission.asked` (dedup by `properties.id`) → `permission`; the island replies `decision` after the user Allow/Deny — the decision round-trip must be live-tested in Phase 3 (see §4/R1).
- `question.asked` → `question`.
- `todo.updated` → `progress` (kept in registry; UI shows `cur/total`).
- `session.idle` / `session.status idle` → `done` (suppressed when a permission/question is pending — pattern already implemented).
- `session.error` → `error`.

Also optional (not required): OpenCode ships a server + SDK (`opencode serve`, `@opencode-ai/sdk`
with a generated client + SSE) that could replace the socket sender for headless/CLI usage.
Not wired in Phase 2; plugin path stays primary because it needs no extra process.

### 2.2 Claude Code — VERIFIED via official docs (code.claude.com/docs/en/hooks)

Hooks are user-defined commands that Claude Code invokes with event JSON on stdin —
the same shape the island needs. Events confirmed relevant:

| Hook event | Fires when | Island mapping |
|---|---|---|
| `SessionStart` | session begins/resumes | `started` |
| `UserPromptSubmit` | user submits a prompt | `working` |
| `PreToolUse` / `PostToolUse` | around each tool call (matcher: tool name, e.g. `Bash|Edit|Write`) | `working` (tool_name + context) |
| `PermissionRequest` | a tool call needs a permission decision | `permission` — **blocking hook can relay island Allow/Deny** |
| `Notification` | native notification events; matchers include `permission_prompt`, `idle_prompt`, `agent_needs_input`, `agent_completed` | `question` / `waiting` |
| `Stop` | Claude finishes responding | `done` |
| `StopFailure` | turn ends on API error (matchable error classes) | `error` |
| `SubagentStart` / `SubagentStop` | subagent spawns/finishes | `working` (parallel sessions) |
| `TaskCreated` / `TaskCompleted` | task list updates | `progress` |
| `PreCompact` / `PostCompact` | compaction | `status` (informational) |

Configuration lives in `~/.claude/settings.json` (user scope) as `hooks.<Event>[]` with optional
`matcher`; command hooks receive JSON on stdin; `${CLAUDE_PROJECT_DIR}` is available to
scripts; `async: true` runs hooks in the background without blocking the agent; HTTP hooks
(`type:"http"` POSTing the event to a local URL) also exist but require a listener process
— the unix socket stays primary.

**Planned sender:** a tiny `claude-send` script (reads stdin JSON, writes one AgentEvents line
to the socket) registered for `SessionStart`, `PreToolUse`/`PostToolUse` (async, tool detail),
`Notification`, `Stop`, `StopFailure`, `TaskCreated/Completed`. Per-event spawn cost
(~30–50 ms) is acceptable and only incurred during real agent activity.

**Interactive permission design (the one risky piece — needs a Phase 3 live-verification gate):**
A **blocking** `PermissionRequest` command hook (no `async`) presents the request to the island
and waits for the user's Allow/Deny on the island's connection; on answer it prints
`{"hookSpecificOutput":{"hookEventName":"PermissionRequest","permissionDecision":"allow|deny",
"permissionDecisionReason":"..."}}`. Verified pieces: hook may emit a JSON decision and Claude
honours it; blocking hooks have a 600 s default timeout. Risk: the hook's decision replaces the
normal interactive terminal prompt; must be opt-in, timeout time-outs to Deny-with-notice, and
must be switchable in settings (fallback: notification-only permissions mode). The exact
decision-outcome schema for `PermissionRequest` (vs `PreToolUse`) needs one live session to
validate before shipping.

### 2.3 Codex CLI (OpenAI) — VERIFIED via web search + official plugins docs (no local install yet)

- `~/.claude` and `~/.codex` do **not exist** here today — the user currently runs OpenCode. Codex/Claude integrations are built and enabled when the user adopts them.

Confirmed mechanisms for future support:

- **`notify` program:** `~/.codex/config.toml` supports a `notify` setting; Codex runs the
  configured program after each completed **agent turn** with the event JSON as `argv[1]`
  (the documented/observed type is `agent-turn-complete`). Community trackers confirm the
  pattern is officially used by telemetry tooling (LangWatch installs a `notify` program; the
  Arize harness implements the same). → Zero-polling `done` signal.
- **Session rollouts:** append-only JSONL transcripts at
  `~/.codex/sessions/YYYY/MM/DD/rollout-*<session_id>.jsonl` (`CODEX_HOME`/`CODEX_SESSIONS_DIR`
  override the root). Each event is a typed record: `session_meta` (id, cwd, originator,
  cli_version), `turn_context` (model), `event_msg`/`token_count`, `response_item`
  (`function_call`/`function_call_output`, `message`), `exec_command_end`/`patch_apply_end`.
  Watching (inotify) on the rollout file of active sessions yields live `working` +
  tool-call detail with no extra agent process. Only watched while a session is active.
- **Approvals:** Codex approval prompts live inside its own TUI — external interactive
  Allow/Deny is NOT feasible. The island shows a **waiting** state derived from notify/rollout
  signals; clicking focuses the terminal instead (INFERRED fallback interaction).

**Planned sender:** `codex-notify` script referenced from `config.toml` (`notify = [...]` argv
form) mapping `agent-turn-complete` → `done`; optional inotify-tail component for `working`.

### 2.4 Extensibility contract (future agents)

Anything that can exec a script on an event can become an Island Pill sender. Senders are
pure functions: event payload (stdin/argv/env) → AgentEvents line → socket. Documented template
+ test fixture so future agents (Gemini CLI, Copilot, local runners) are config, not code.

---

## 3. Session registry (server side)

The island's `agents` module maintains:

- `sessions: { key: agent:session → {agent, project, state, state_ts, title, detail, progress, waiting?} }`
- `most recent state change wins` for the primary UI focus;
- permission counter per session (queued decisions — TwoCode shows `1/2` steps);
- a capped ordered history feed (also the "history" surface of Doc 04);
- suppression rules already proven in the current plugin/bridge pair:
  `done` suppressed while a permission/question is pending in that session (pending set per
  sessionID, as in `island-pill-notify.js`);

Dedup/ACK semantics and validation live in a **pure `protocol` module** (no GLib imports so it
is fully headless-unit-testable), mirroring how the current tests cover peek/dedup logic.

---

## 4. Risks & verification gates (before integration is considered "done")

| # | Risk | Mitigation / gate |
|---|---|---|
| R1 | Claude PermissionRequest decision schema differs from our belief | Phase 3 live-session spike; fallback = notification-only mode (no hook blocking) |
| R2 | Socket abuse/permissions | existing measures kept: 0600 socket, owned-XDG check, message cap, timeout |
| R3 | Codex rollout JSONL format drifts between versions | tailer version-tolerant: parse unknown-record types defensively |
| R4 | OpenCode major upgrades change the plugin API | plugin pinned to documented `event` hook only; integration tests with fixture events |
| R5 | Multiple agents at once (different projects) | registry keyed by agent+session; UI picks most-recent-state session; expanded card shows all |
