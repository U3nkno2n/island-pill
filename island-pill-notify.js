import { createConnection } from "node:net";
import { appendFileSync } from "node:fs";

const SOCKET_PATH = process.env.XDG_RUNTIME_DIR
  ? `${process.env.XDG_RUNTIME_DIR}/island-pill.sock`
  : null;

const DEDUP_TTL = 5000; // ms
const CONNECT_TIMEOUT = 500; // ms

const DEBUG_LOG = process.env.XDG_RUNTIME_DIR
  ? `${process.env.XDG_RUNTIME_DIR}/island-pill-opencode-debug.log`
  : null;

const debugLog = (tag, fields = {}) => {
  if (!DEBUG_LOG) return;
  const parts = [new Date().toISOString(), tag];
  for (const [k, v] of Object.entries(fields)) {
    parts.push(`${k}=${String(v)}`);
  }
  try { appendFileSync(DEBUG_LOG, parts.join(" | ") + "\n"); } catch {}
};

debugLog("plugin-loaded", { export: "server" });

// sessionID -> Set of requestIDs awaiting input
const pending = new Map();
// dedup key -> timestamp
const dedup = new Map();
// Sessions that already announced their one "working" peek for the current
// turn: further activity events stay silent until the turn ends.
const busy = new Set();

const now = () => Date.now();

const dedupKey = (type, sessionID, requestID) =>
  `${type}:${sessionID}:${requestID || ""}`;

const isStale = (key) => {
  const t = dedup.get(key);
  return t === undefined || now() - t > DEDUP_TTL;
};

const markDedup = (key) => {
  dedup.set(key, now());
  const cutoff = now() - DEDUP_TTL * 2;
  for (const [k, v] of dedup.entries()) {
    if (v < cutoff) dedup.delete(k);
  }
};

const sendControl = (payload) => {
  if (!SOCKET_PATH) {
    debugLog("socket-send", { result: "no-socket-path" });
    return;
  }
  if (!controlSock || controlSock.destroyed) {
    connectControl();
    return;
  }
  try {
    controlSock.write(JSON.stringify(payload) + "\n");
    debugLog("socket-send", { result: "written" });
  } catch {
    debugLog("socket-send", { result: "write-error" });
    controlSock = null;
  }
};

// Persistent control connection to the Island Pill bridge.
// Used for sending events and receiving opencode.decision replies.
let controlSock = null;
let controlBuffer = "";

// Outbound message queue used while the control socket is down or
// reconnecting.  Messages are flushed in order once connected.
const sendQueue = [];
const MAX_SEND_QUEUE = 50;
// Logged once per outage so the debug log is not flooded with one line
// per dropped message.
let socketOfflineLogged = false;

// Pending permission requests awaiting a decision from the island.
// reqid -> { resolve, timer }
const pendingPermissions = new Map();
const PERMISSION_TIMEOUT_MS = 30000;

function connectControl() {
  if (!SOCKET_PATH) return;
  if (controlSock && !controlSock.destroyed) return;
  controlSock = createConnection({ path: SOCKET_PATH });
  controlSock.setTimeout(0);
  controlSock.unref();
  controlSock.on("connect", () => {
    debugLog("control-connect", { result: "connected" });
    socketOfflineLogged = false;
    try {
      controlSock.write(JSON.stringify({ type: "control", agent: "opencode" }) + "\n");
    } catch {}
    // Flush any queued messages in order once connected.
    while (sendQueue.length) {
      const next = sendQueue.shift();
      try {
        controlSock.write(next);
      } catch {
        controlSock = null;
        break;
      }
    }
  });
  controlSock.on("data", (data) => {
    controlBuffer += data.toString();
    let idx;
    while ((idx = controlBuffer.indexOf("\n")) !== -1) {
      const line = controlBuffer.slice(0, idx);
      controlBuffer = controlBuffer.slice(idx + 1);
      try {
        const msg = JSON.parse(line);
        if (msg && msg.type === "opencode.decision") {
          const { session, reqid, decision } = msg;
          const pending = pendingPermissions.get(reqid);
          if (pending) {
            pendingPermissions.delete(reqid);
            if (pending.timer) { clearTimeout(pending.timer); pending.timer = null; }
            pending.resolve(decision === "allow" ? "allow" : "deny");
          }
        }
      } catch {}
    }
  });
  controlSock.on("error", () => {
    debugLog("control-error", {});
    controlSock = null;
  });
  controlSock.on("close", () => {
    debugLog("control-close", {});
    controlSock = null;
    // Bridge disconnected: fall back to OpenCode's normal prompt.
    for (const [reqid, pending] of pendingPermissions) {
      pendingPermissions.delete(reqid);
      if (pending.timer) { clearTimeout(pending.timer); pending.timer = null; }
      pending.resolve("ask");
    }
  });
}

function sendEvent(payload) {
  if (!SOCKET_PATH) {
    debugLog("socket-send", { result: "no-socket-path" });
    return;
  }
  const line = JSON.stringify(payload) + "\n";
  if (!controlSock || controlSock.destroyed) {
    // Queue the message and retry once connected; never silently drop.
    if (sendQueue.length >= MAX_SEND_QUEUE) {
      sendQueue.shift(); // drop oldest
    }
    sendQueue.push(line);
    if (!socketOfflineLogged) {
      debugLog("socket-offline", { result: "reconnecting" });
      socketOfflineLogged = true;
    }
    connectControl();
    return;
  }
  socketOfflineLogged = false;
  try {
    controlSock.write(line);
    debugLog("socket-send", { result: "written" });
  } catch {
    debugLog("socket-send", { result: "write-error" });
    controlSock = null;
  }
}

// Answer an OpenCode permission request via the island pill.
// Returns a promise that resolves to "allow", "deny", or "ask" (fallback).
// The permission.ask hook and the permission.asked event carry the same
// reqid, so the second caller reuses the first caller's pending entry
// instead of sending a second message.
function permissionAsk(input, projectName) {
  const reqid = input && input.id ? String(input.id) : "";
  const session = input && input.sessionID ? String(input.sessionID) : "";
  if (reqid && pendingPermissions.has(reqid)) {
    return pendingPermissions.get(reqid).promise;
  }
  let resolveFn;
  const promise = new Promise((resolve) => { resolveFn = resolve; });
  sendEvent({
    type: "permission",
    session: session,
    reqid: reqid,
    project: projectName,
    title: input.title,
    detail: input.type + (input.pattern ? ": " + input.pattern : ""),
    ts: Date.now(),
  });
  const timer = setTimeout(() => {
    pendingPermissions.delete(reqid);
    resolveFn("ask");
  }, PERMISSION_TIMEOUT_MS);
  pendingPermissions.set(reqid, { resolve: resolveFn, timer, promise });
  return promise;
}

// Establish the control connection on module load.
connectControl();

// OpenCode 1.19.5 plugin entry point. Receives PluginInput and returns Hooks.
export const server = async ({ project, client, directory, worktree }) => {
  const baseName = (p) =>
    p ? (String(p).split("/").filter(Boolean).pop() || "") : "";
  let projectName =
    (typeof project === "object" && project && project.name)
      ? String(project.name)
      : "";
  if (!projectName) projectName = baseName(worktree);
  if (!projectName) projectName = baseName(directory);
  if (!projectName) projectName = baseName(process.cwd());
  if (!projectName) projectName = "OpenCode";

  debugLog("server-called", {
    project: typeof project === "object" && project ? project.id : "",
    worktree,
    directory,
    projectName,
  });

  const notify = (type, title, body, level) => {
    sendEvent({
      type,
      title,
      body,
      level,
      project: projectName,
      session: "",
    });
  };

  const hooks = {
    event: async (input) => {
      debugLog("event-hook-called", { inputType: typeof input });
      if (!input || typeof input !== "object") {
        debugLog("event-ignored", { reason: "non-object", type: "", sessionID: "" });
        return;
      }
      const { event } = input;
      if (!event || typeof event !== "object") {
        debugLog("event-ignored", { reason: "non-object", type: "", sessionID: "" });
        return;
      }
      const { type, properties } = event;
      if (!type || typeof type !== "string") {
        debugLog("event-ignored", { reason: "missing-type", type: "", sessionID: "" });
        return;
      }
      if (!properties || typeof properties !== "object") {
        debugLog("event-ignored", { reason: "missing-properties", type, sessionID: "" });
        return;
      }

      const sessionID = properties.sessionID || "";
      debugLog("event-received", { type, sessionID });

      // ---------- session created ----------
      if (type === "session.created") {
        const key = dedupKey(type, sessionID, "");
        if (!isStale(key)) {
          debugLog("event-ignored", { reason: "dedup-hit", type, sessionID });
          return;
        }
        markDedup(key);
        debugLog("notify-called", { ntype: "opencode", sessionID });
        sendEvent({
          type: "started",
          session: sessionID,
          reqid: "",
          project: projectName,
          title: "OpenCode · Session started",
          body: "OpenCode started working",
          ts: Date.now(),
        });
        return;
      }

      // ---------- tool activity ----------
      if (type === "message.part.updated" ||
          type === "tool.execute.before" ||
          type === "tool.execute.after") {
        // One "working" peek when the turn starts; silence while it continues.
        if (busy.has(sessionID)) {
          debugLog("event-ignored", { reason: "session-busy", type, sessionID });
          return;
        }
        busy.add(sessionID);
        debugLog("notify-called", { ntype: "opencode", sessionID });
        sendEvent({
          type: "working",
          session: sessionID,
          reqid: properties.id || "",
          project: projectName,
          title: "OpenCode · Working",
          body: projectName,
          ts: Date.now(),
        });
        return;
      }

      // ---------- permission requested ----------
      if (type === "permission.asked" || type === "permission.updated") {
        const requestID = properties.id || properties.permissionID || "";
        const key = dedupKey(type, sessionID, requestID);
        if (!isStale(key)) {
          debugLog("event-ignored", { reason: "dedup-hit", type, sessionID });
          return;
        }
        markDedup(key);
        if (!pending.has(sessionID)) pending.set(sessionID, new Set());
        pending.get(sessionID).add(requestID);
        const permission = {
          id: requestID,
          type: properties.permission || properties.type || "permission",
          pattern: properties.pattern,
          sessionID: sessionID,
          messageID: properties.messageID || "",
          callID: properties.callID,
          title: properties.title || "Permission",
          metadata: properties.metadata || {},
          time: { created: Date.now() },
        };
        debugLog("notify-called", { ntype: "opencode-alert", sessionID, requestID });
        // Ask the island pill for a decision; await it before replying to OpenCode.
        permissionAsk(permission, projectName).then(async (status) => {
          const s = pending.get(sessionID);
          if (s) {
            s.delete(requestID);
            if (s.size === 0) pending.delete(sessionID);
          }
          debugLog("permission-decided", { requestID, status });
          // The permission.ask hook answers via output.status; also reply
          // through the SDK here in case the hook is never invoked, so an
          // island decision still counts.  Answering twice or against an
          // already-processed permission must not break anything, so errors
          // are logged and swallowed.
          if (status === "allow" || status === "deny") {
            const response = status === "allow" ? "once" : "reject";
            try {
              await client.postSessionIdPermissionsPermissionId({
                path: { id: sessionID, permissionID: requestID },
                body: { response: response },
              });
              debugLog("permission-reply-ok", { requestID, response: response });
            } catch (e) {
              debugLog("permission-reply-error", {
                requestID,
                error: e && e.message ? e.message : String(e),
              });
            }
          }
        }).catch((e) => {
          const s = pending.get(sessionID);
          if (s) {
            s.delete(requestID);
            if (s.size === 0) pending.delete(sessionID);
          }
          debugLog("permission-event-error", {
            requestID,
            error: e && e.message ? e.message : String(e),
          });
        });
        return;
      }

      // ---------- permission answered ----------
      if (type === "permission.replied" || type === "permission.rejected") {
        const requestID = properties.id || properties.permissionID || "";
        const key = dedupKey(type, sessionID, requestID);
        if (!isStale(key)) {
          debugLog("event-ignored", { reason: "dedup-hit", type, sessionID });
          return;
        }
        markDedup(key);
        const s = pending.get(sessionID);
        if (s) {
          s.delete(requestID);
          if (s.size === 0) pending.delete(sessionID);
        }
        return;
      }

      // ---------- question asked ----------
      if (type === "question.asked") {
        const requestID = properties.id || "";
        const key = dedupKey(type, sessionID, requestID);
        if (!isStale(key)) {
          debugLog("event-ignored", { reason: "dedup-hit", type, sessionID });
          return;
        }
        markDedup(key);
        if (!pending.has(sessionID)) pending.set(sessionID, new Set());
        pending.get(sessionID).add(requestID);
        const questions = Array.isArray(properties.questions)
          ? properties.questions
          : [];
        const q = questions[0] || {};
        const text = q.header || q.question || "Question";
        debugLog("notify-called", { ntype: "opencode-alert", sessionID });
        notify(
          "opencode-alert",
          `Question · ${projectName}`,
          text,
          "attention",
        );
        return;
      }

      // ---------- question answered ----------
      if (type === "question.replied" || type === "question.rejected") {
        const requestID = properties.id || properties.requestID || "";
        const key = dedupKey(type, sessionID, requestID);
        if (!isStale(key)) {
          debugLog("event-ignored", { reason: "dedup-hit", type, sessionID });
          return;
        }
        markDedup(key);
        const s = pending.get(sessionID);
        if (s) {
          s.delete(requestID);
          if (s.size === 0) pending.delete(sessionID);
        }
        return;
      }

      // ---------- session error ----------
      if (type === "session.error") {
        busy.delete(sessionID);
        const errorName = (properties.error && properties.error.name) || "Error";
        const errorMsg =
          properties.error &&
          properties.error.data &&
          typeof properties.error.data === "object"
            ? properties.error.data.message || ""
            : "";
        const key = dedupKey(type, sessionID, String(errorName));
        if (!isStale(key)) {
          debugLog("event-ignored", { reason: "dedup-hit", type, sessionID });
          return;
        }
        markDedup(key);
        debugLog("notify-called", { ntype: "opencode-error", sessionID });
        sendEvent({
          type: "failed",
          session: sessionID,
          reqid: "",
          project: projectName,
          title: "OpenCode · Error",
          body: `${errorName}${errorMsg ? ": " + errorMsg : ""}`,
          ts: Date.now(),
        });
        return;
      }

      // ---------- session idle (completion) ----------
      if (type === "session.idle") {
        busy.delete(sessionID);   // the working phase is over either way
        // Suppress if the session is awaiting user input.
        const s = pending.get(sessionID);
        if (s && s.size > 0) {
          debugLog("event-ignored", { reason: "pending-suppressed", type, sessionID });
          return;
        }
        const key = dedupKey(type, sessionID, "");
        if (!isStale(key)) {
          debugLog("event-ignored", { reason: "dedup-hit", type, sessionID });
          return;
        }
        markDedup(key);
        debugLog("notify-called", { ntype: "opencode", sessionID });
        sendEvent({
          type: "done",
          session: sessionID,
          reqid: "",
          project: projectName,
          title: "OpenCode · Response finished",
          body: "Assistant response completed",
          ts: Date.now(),
        });
        return;
      }

      // ---------- session status idle (completion) ----------
      if (type === "session.status" && properties.status && properties.status.type === "idle") {
        busy.delete(sessionID);   // the working phase is over either way
        // Suppress if the session is awaiting user input.
        const s = pending.get(sessionID);
        if (s && s.size > 0) {
          debugLog("event-ignored", { reason: "pending-suppressed", type, sessionID });
          return;
        }
        const key = dedupKey("session.idle", sessionID, "");
        if (!isStale(key)) {
          debugLog("event-ignored", { reason: "dedup-hit", type, sessionID });
          return;
        }
        markDedup(key);
        debugLog("notify-called", { ntype: "opencode", sessionID });
        sendEvent({
          type: "done",
          session: sessionID,
          reqid: "",
          project: projectName,
          title: "OpenCode · Response finished",
          body: "Assistant response completed",
          ts: Date.now(),
        });
        return;
      }
    },
    "permission.ask": async (input, output) => {
      // Forward the permission request to the island pill and await the
      // user's Allow / Deny decision.  If the island is unavailable or the
      // request times out, fall back to "ask" so OpenCode uses its normal
      // terminal prompt.
      try {
        output.status = await permissionAsk(input, projectName);
      } catch (e) {
        debugLog("permission-hook-error", {
          error: e && e.message ? e.message : String(e),
        });
        output.status = "ask";
      }
    },
  };

  return hooks;
};
