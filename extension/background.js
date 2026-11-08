const BASE = "http://127.0.0.1:8765";
const VERSION = "9";

class BridgeError extends Error {
  constructor(message, code = "") {
    super(message);
    this.code = code;
  }
}

async function call(path, body, token) {
  let r;
  try {
    r = await fetch(BASE + path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "content-type": "application/json", ...(token ? { "x-sahl-ext-token": token } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new BridgeError("Sahl isn't running, or its browser bridge is blocked. Open Sahl and try again.", "closed");
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new BridgeError(data.detail || `Sahl returned ${r.status}`, r.status === 403 ? "pair" : "");
  return data;
}

async function storedToken() {
  const { token } = await chrome.storage.local.get("token");
  return token || "";
}

async function inject(tabId) {
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
  } catch {
    throw new BridgeError("This page can't be read. Open a normal web page, not a browser settings page.", "tab");
  }
}

function metadata(page) {
  return {
    ...page,
    fields: (page.fields || []).map((f) => ({
      ...f,
      options: (f.options || []).map((o) => ({ text: o.text, selected: Boolean(o.selected) })),
    })),
  };
}

async function endReading(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: `sahl:v${VERSION}:read-end` });
  } catch {}
}

async function scan(tabId, person, strings) {
  const token = await storedToken();
  if (!token) throw new BridgeError("Pair with Sahl first.", "pair");
  await inject(tabId);
  let page;
  try {
    page = await chrome.tabs.sendMessage(tabId, { type: `sahl:v${VERSION}:scan`, strings });
  } catch {
    await endReading(tabId);
    throw new BridgeError("Couldn't read this page. Reload it and try again.", "tab");
  }
  if (!page) {
    await endReading(tabId);
    throw new BridgeError("This page has no form Sahl can read.", "empty");
  }
  let plan;
  try {
    plan = await call("/page", { ...metadata(page), person: person || null }, token);
  } catch (e) {
    await endReading(tabId);
    throw e;
  }
  try {
    await chrome.tabs.sendMessage(tabId, { type: `sahl:v${VERSION}:render`, fields: plan.fields || [], strings });
  } catch {
    await endReading(tabId);
  }
  return plan;
}

async function fill(tabId, ids, person, replace) {
  const token = await storedToken();
  if (!token) throw new BridgeError("Pair with Sahl first.", "pair");
  const released = await call("/values", { element_ids: ids, person: person || null }, token);
  let results = [];
  if (released.values?.length) {
    try {
      results = await chrome.tabs.sendMessage(tabId, { type: `sahl:v${VERSION}:fill`, values: released.values, replace: Boolean(replace) });
    } catch {
      throw new BridgeError("The page changed. Scan it again.", "tab");
    }
  }
  return { results, missing: released.missing || [], needs_person: Boolean(released.needs_person) };
}

// a box no guide knows: what the person typed for it, or that it is a detail they told Sahl under another name
async function tell(path, body) {
  const token = await storedToken();
  if (!token) throw new BridgeError("Pair with Sahl first.", "pair");
  return call(path, body, token);
}

async function health() {
  try {
    return await call("/health");
  } catch (e) {
    return { error: e.message, code: e.code };
  }
}

async function pair(code) {
  const out = await call("/pair", { code: String(code || "").trim(), name: "Sahl browser" });
  await chrome.storage.local.set({ token: out.token });
  return { ok: true };
}

async function clear(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: `sahl:v${VERSION}:clear` });
  } catch {}
  const token = await storedToken();
  if (token) await call("/clear", {}, token).catch(() => {});
  return { ok: true };
}

async function handled(msg) {
  if (msg?.type === "health") return health();
  if (msg?.type === "pair") return pair(msg.code);
  if (msg?.type === "scan") return scan(msg.tabId, msg.person, msg.strings || {});
  if (msg?.type === "fill") return fill(msg.tabId, msg.ids || [], msg.person, msg.replace);
  if (msg?.type === "tell") return tell("/taught", { element_id: msg.id, value: msg.value, person: msg.person || null });
  if (msg?.type === "same") return tell("/taught/alias", { element_id: msg.id, concept: msg.concept });
  // the person answered an amber box on the page itself: remember it, or forget it again on Undo
  if (msg?.type === "learn") return tell("/taught", { element_id: msg.id, value: msg.value, person: null });
  if (msg?.type === "unlearn") return tell("/taught/forget", { concept: msg.concept });
  if (msg?.type === "clear") return clear(msg.tabId);
  if (msg?.type === "token") return { token: Boolean(await storedToken()) };
  throw new BridgeError("Unknown request", "internal");
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  handled(msg)
    .then((out) => reply({ ok: true, ...out }))
    .catch((e) => reply({ ok: false, error: e.message || String(e), code: e.code || "" }));
  return true;
});

