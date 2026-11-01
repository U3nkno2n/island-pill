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

const send = (payload) => {
  if (!SOCKET_PATH) {
    debugLog("socket-send", { result: "no-socket-path" });
    return;
  }
  try {
    const sock = createConnection({ path: SOCKET_PATH });
    sock.setTimeout(CONNECT_TIMEOUT);
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      try { sock.destroy(); } catch {}
    };
    sock.on("connect", () => {
      try {
        sock.write(JSON.stringify(payload) + "\n");
        debugLog("socket-send", { result: "written" });
      } catch {
        debugLog("socket-send", { result: "write-error" });
      }
    });
    sock.on("error", () => {
      debugLog("socket-send", { result: "connect-error" });
      finish();
    });
    sock.on("timeout", () => {
      debugLog("socket-send", { result: "timeout" });
      finish();
    });
    sock.on("close", finish);
    try { sock.unref(); } catch {}
  } catch {
    debugLog("socket-send", { result: "create-error" });
  }
};

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
    send({
      type,
      title,
      body,
      level,
      project: projectName,
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
        const permission =
          properties.permission || properties.type || "permission";
        const patterns = Array.isArray(properties.patterns)
          ? properties.patterns.join(", ")
          : properties.pattern || "";
        debugLog("notify-called", { ntype: "opencode-alert", sessionID });
        notify(
          "opencode-alert",
          `Permission · ${projectName}`,
          `${permission}${patterns ? ": " + patterns : ""}`,
          "attention",
        );
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
        notify(
          "opencode-error",
          `Error · ${projectName}`,
          `${errorName}${errorMsg ? ": " + errorMsg : ""}`,
          "attention",
        );
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
        notify(
          "opencode",
          `Response finished · ${projectName}`,
          "Assistant response completed",
          "info",
        );
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
        notify(
          "opencode",
          `Response finished · ${projectName}`,
          "Assistant response completed",
          "info",
        );
        return;
      }
    },
  };

  return hooks;
};
