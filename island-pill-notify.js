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
    try {
      controlSock.write(JSON.stringify({ type: "control", agent: "opencode" }) + "\n");
    } catch {}
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
}

// Answer an OpenCode permission request via the island pill.
// Returns a promise that resolves to "allow", "deny", or "ask" (fallback).
function permissionAsk(input) {
  return new Promise((resolve) => {
    const reqid = input.id || "";
    const session = input.sessionID || "";
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
      resolve("ask");
    }, PERMISSION_TIMEOUT_MS);
    pendingPermissions.set(reqid, { resolve, timer });
  });
}

// Establish the control connection on module load.
connectControl();

// OpenCode 1.19.5 plugin entry point. Receives PluginInput and returns Hooks.
export const server = async ({ project, client, directory, worktree }) => {
  const projectName =
    (typeof project === "object" && project && project.name)
      ? String(project.name)
      : worktree
        ? worktree.split("/").pop()
        : directory
          ? directory.split("/").pop()
          : process.cwd().split("/").pop() || "";

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
        const key = dedupKey(type, sessionID, properties.id || "");
        if (!isStale(key)) {
          debugLog("event-ignored", { reason: "dedup-hit", type, sessionID });
          return;
        }
        markDedup(key);
        const toolName = properties.tool || properties.name || "tool";
        const detail = properties.input || properties.output || "";
        debugLog("notify-called", { ntype: "opencode", sessionID });
        sendEvent({
          type: "working",
          session: sessionID,
          reqid: properties.id || "",
          project: projectName,
          title: "OpenCode · Working",
          body: toolName + (detail ? ": " + String(detail).slice(0, 80) : ""),
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
        permissionAsk(permission).then((status) => {
          const s = pending.get(sessionID);
          if (s) {
            s.delete(requestID);
            if (s.size === 0) pending.delete(sessionID);
          }
          debugLog("permission-decided", { requestID, status });
        }).catch(() => {
          const s = pending.get(sessionID);
          if (s) {
            s.delete(requestID);
            if (s.size === 0) pending.delete(sessionID);
          }
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
        output.status = await permissionAsk(input);
      } catch {
        output.status = "ask";
      }
    },
  };

  return hooks;
};
