// node:test suite for island-pill-notify.js permission handling.
// No new dependencies: uses node:test, node:net, node:assert/strict.
//
// The plugin reads XDG_RUNTIME_DIR and its plugin entry (.js with ESM export)
// at import time, so before importing we (1) point XDG_RUNTIME_DIR at a temp
// dir and (2) copy the plugin to plugin.mjs so ESM parsing never depends on
// package.json type detection.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "island-pill-plugin-test-"));
process.env.XDG_RUNTIME_DIR = tmp;
const socketPath = path.join(tmp, "island-pill.sock");

// ---- fake Island Pill bridge ------------------------------------------------
// Receives every JSON line the plugin sends over its control socket and lets
// the tests push opencode.decision replies back through the same connection.
let serverConn = null;
const received = [];
const waiters = [];

const bridgeServer = net.createServer((conn) => {
  serverConn = conn;
  let buf = "";
  conn.on("data", (d) => {
    buf += d.toString("utf8");
    let i;
    while ((i = buf.indexOf("\n")) !== -1) {
      const line = buf.slice(0, i);
      buf = buf.slice(i + 1);
      let msg;
      try { msg = JSON.parse(line); } catch { continue; }
      received.push(msg);
      for (const w of waiters.slice()) w();
    }
  });
});

await new Promise((resolve, reject) => {
  bridgeServer.once("error", reject);
  bridgeServer.listen(socketPath, resolve);
});

// Waits for the next matching line coming FROM the plugin over the socket.
const waitFor = (filter, ms = 2000) => {
  const hit = () => received.find(filter);
  if (hit()) return Promise.resolve(hit());
  return new Promise((resolve, reject) => {
    const w = () => {
      const m = hit();
      if (m) {
        const i = waiters.indexOf(w);
        if (i >= 0) waiters.splice(i, 1);
        resolve(m);
      }
    };
    waiters.push(w);
    setTimeout(
      () => {
        const i = waiters.indexOf(w);
        if (i >= 0) waiters.splice(i, 1);
        reject(new Error("timeout waiting for bridge message"));
      },
      ms,
    ).unref();
  });
};

// Polls any in-process condition (e.g. the fake client being called): the
// SDK reply does not travel over the socket, so it cannot be waited for via
// waitFor().
const settle = (ms = 20) => new Promise((r) => setTimeout(r, ms));

const until = async (cond, ms = 2000) => {
  const start = Date.now();
  while (!cond()) {
    if (Date.now() - start > ms) {
      throw new Error("timeout waiting for condition");
    }
    await settle();
  }
};

const decide = (session, reqid, decision) => {
  assert.ok(serverConn, "no bridge connection from the plugin");
  serverConn.write(
    JSON.stringify({ type: "opencode.decision", session, reqid, decision }) +
      "\n",
  );
};

// ---- import the plugin ------------------------------------------------------
const pluginSrc = fileURLToPath(new URL("../island-pill-notify.js", import.meta.url));
const pluginCopy = path.join(tmp, "plugin.mjs");
fs.writeFileSync(pluginCopy, fs.readFileSync(pluginSrc, "utf8"));
const plugin = await import(pathToFileURL(pluginCopy).href);

// ---- fake OpenCode client ---------------------------------------------------
const sdkCalls = [];
const fakeClient = {
  postSessionIdPermissionsPermissionId: async (opts) => {
    sdkCalls.push(opts);
    return { status: 200, data: {} };
  },
};

// Non-git project: empty project object, empty worktree -> directory basename.
const hooks = await plugin.server({
  project: null,
  client: fakeClient,
  directory: "/tmp/permission-test/",
  worktree: "",
});

const askEvent = (reqid, sessionID = "ses_t", type = "bash") =>
  hooks.event({
    event: {
      type: "permission.asked",
      properties: {
        id: reqid,
        type,
        sessionID,
        title: "Run bash command",
        pattern: "*",
        metadata: {},
      },
    },
  });

test("permission.asked reaches the bridge with a non-empty project", async () => {
  await askEvent("per_1", "ses_1");
  const msg = await waitFor(
    (m) => m.type === "permission" && m.reqid === "per_1",
  );
  assert.equal(msg.type, "permission");
  assert.equal(msg.session, "ses_1");
  assert.ok(msg.project && msg.project.length > 0, "project must be non-empty");
});

test("island allow decision replies to OpenCode with once", async () => {
  decide("ses_1", "per_1", "allow");
  await until(() => sdkCalls.some((o) => o.path.permissionID === "per_1"));
  assert.equal(
    sdkCalls.filter((o) => o.path.permissionID === "per_1").length,
    1,
    "the OpenCode client must be called exactly once for allow",
  );
  const call = sdkCalls.find((o) => o.path.permissionID === "per_1");
  assert.deepEqual(call.path, { id: "ses_1", permissionID: "per_1" });
  assert.deepEqual(call.body, { response: "once" });
});

test("island deny decision replies to OpenCode with reject", async () => {
  await askEvent("per_2", "ses_2");
  await waitFor((m) => m.type === "permission" && m.reqid === "per_2");
  decide("ses_2", "per_2", "deny");
  await until(() => sdkCalls.some((o) => o.path.permissionID === "per_2"));
  const call = sdkCalls.find((o) => o.path.permissionID === "per_2");
  assert.deepEqual(call.body, { response: "reject" });
});

test("same reqid via event and hook sends only one message", async () => {
  await askEvent("per_3", "ses_3");
  await waitFor((m) => m.type === "permission" && m.reqid === "per_3");
  const out = {};
  const hookP = hooks["permission.ask"](
    { id: "per_3", type: "bash", sessionID: "ses_3", title: "Run bash command" },
    out,
  );
  await settle();
  const count = received.filter(
    (m) => m.type === "permission" && m.reqid === "per_3",
  ).length;
  assert.equal(count, 1, "shared reqid must produce exactly one message");
  decide("ses_3", "per_3", "allow");
  await hookP;
  assert.equal(out.status, "allow");
});

test("permission.ask hook alone answers and does not duplicate messages", async () => {
  // Event path with the hook ALSO registered for a different session id:
  // both share per_4; hook resolves from the single island decision.
  await askEvent("per_4", "ses_4");
  await waitFor((m) => m.type === "permission" && m.reqid === "per_4");
  const out = {};
  const hookP = hooks["permission.ask"](
    { id: "per_4", type: "bash", sessionID: "ses_4", title: "Run bash command" },
    out,
  );
  await settle();
  assert.equal(
    received.filter((m) => m.type === "permission" && m.reqid === "per_4").length,
    1,
  );
  decide("ses_4", "per_4", "deny");
  await hookP;
  assert.equal(out.status, "deny");
});

test("announceClosed sends closed for each seen session", async () => {
  await hooks.event({ event: { type: "session.created", properties: { sessionID: "ac_ses_a", id: "ac_ses_a" } } });
  await hooks.event({ event: { type: "session.created", properties: { sessionID: "ac_ses_b", id: "ac_ses_b" } } });
  // Empty session id must not be recorded.
  await hooks.event({ event: { type: "session.created", properties: { sessionID: "", id: "" } } });

  plugin.server.announceClosed();
  await settle(50);

  const closedMsgs = received.filter(m => m.type === "closed" && ["ac_ses_a", "ac_ses_b"].includes(m.session));
  assert.equal(closedMsgs.length, 2, "each seen session must get a closed message");
  assert.ok(closedMsgs.some(m => m.session === "ac_ses_a"));
  assert.ok(closedMsgs.some(m => m.session === "ac_ses_b"));
});

test("session.deleted announces only the deleted session", async () => {
  await hooks.event({ event: { type: "session.created", properties: { sessionID: "sd_ses_x", id: "sd_ses_x" } } });
  await hooks.event({ event: { type: "session.created", properties: { sessionID: "sd_ses_y", id: "sd_ses_y" } } });

  // Delete only ses_x via info.id
  await hooks.event({ event: { type: "session.deleted", properties: { info: { id: "sd_ses_x" }, sessionID: "sd_ses_x" } } });
  await settle(50);

  const closedMsgs = received.filter(m => m.type === "closed" && ["sd_ses_x", "sd_ses_y"].includes(m.session));
  assert.equal(closedMsgs.length, 1, "session.deleted must announce only the deleted session");
  assert.equal(closedMsgs[0].session, "sd_ses_x");
});

test("session.deleted falls back to sessionID when info.id is missing", async () => {
  await hooks.event({ event: { type: "session.created", properties: { sessionID: "sd_ses_z", id: "sd_ses_z" } } });

  await hooks.event({ event: { type: "session.deleted", properties: { sessionID: "sd_ses_z" } } });
  await settle(50);

  const closedMsgs = received.filter(m => m.type === "closed" && m.session === "sd_ses_z");
  assert.equal(closedMsgs.length, 1, "session.deleted must fall back to properties.sessionID");
});

test("permission.replied is forwarded to the island", async () => {
  await hooks.event({ event: { type: "permission.replied", properties: { requestID: "pr_1", sessionID: "ses_r" } } });

  const msg = await waitFor((m) => m.type === "permission.replied" && m.session === "ses_r" && m.reqid === "pr_1");
  assert.equal(msg.type, "permission.replied");
  assert.equal(msg.session, "ses_r");
  assert.equal(msg.reqid, "pr_1");
});

test("messages sent while disconnected flush in order after reconnect", async () => {
  // Drop the control connection and stop listening so sendEvent queues.
  serverConn.destroy();
  bridgeServer.close(() => {});
  await settle(100);

  // Send messages while the control socket is down - they must be queued,
  // not dropped. Small delays between sends let each failed connectControl
  // attempt (error -> controlSock = null) complete before the next send.
  await hooks.event({ event: { type: "permission.asked", properties: { id: "q1", type: "bash", sessionID: "sq1", title: "Q1", pattern: "*", metadata: {} } } });
  await settle(100);
  await hooks.event({ event: { type: "permission.asked", properties: { id: "q2", type: "bash", sessionID: "sq2", title: "Q2", pattern: "*", metadata: {} } } });
  await settle(100);
  await hooks.event({ event: { type: "permission.asked", properties: { id: "q3", type: "bash", sessionID: "sq3", title: "Q3", pattern: "*", metadata: {} } } });
  await settle(100);

  // None of the queued messages reached the bridge (server not listening).
  const before = received.filter(m => m.type === "permission" && ["q1","q2","q3"].includes(m.reqid)).length;
  assert.equal(before, 0, "no message should reach the bridge while disconnected");

  // Restart the bridge server on the same socket path.
  try { fs.unlinkSync(socketPath); } catch {}
  await new Promise((resolve, reject) => {
    bridgeServer.once("error", reject);
    bridgeServer.listen(socketPath, resolve);
  });
  await settle(100);

  // One more event triggers connectControl, which reconnects and flushes
  // the queued messages in order.
  await hooks.event({ event: { type: "permission.asked", properties: { id: "q4", type: "bash", sessionID: "sq4", title: "Q4", pattern: "*", metadata: {} } } });

  // All four messages must arrive in order: q1, q2, q3, q4.
  await until(() => {
    const perms = received.filter(m => m.type === "permission" && ["q1","q2","q3","q4"].includes(m.reqid));
    return perms.length === 4;
  }, 2000);

  const order = received
    .filter(m => m.type === "permission" && ["q1","q2","q3","q4"].includes(m.reqid))
    .map(m => m.reqid);
  assert.deepEqual(order, ["q1", "q2", "q3", "q4"]);
});

// ---- teardown ---------------------------------------------------------------
after(() => {
  try {
    if (serverConn) serverConn.destroy();
  } catch {}
  bridgeServer.close(() => {});
  waiters.length = 0;
  try { fs.rmSync(tmp, { recursive: true, force: true }); } catch {}
  // Every permission in the tests gets a decision, so the plugin's 30 s
  // permission timers are all cleared and the process should drain by itself.
  // Belt-and-braces: if anything still holds the event loop (a leftover
  // timer would be a bug), exit after a grace period instead of hanging.
  const t = setTimeout(() => {
    console.error("plugin_permission tests did not drain; forcing exit");
    process.exit(1);
  }, 300);
  t.unref();
});
