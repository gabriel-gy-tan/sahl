// Sahl's bridge takes the first free port of this range (sidecar/sahl/bridge.py PORTS); manifest.json lists the same ones
const PORTS = [8765, 8766, 8767, 8768, 8769, 8770, 8771, 8772, 8773, 8774];
const PROBE_MS = 1500;
const VERSION = "8";

class BridgeError extends Error {
  constructor(message, code = "") {
    super(message);
    this.code = code;
  }
}

const hex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");

async function proofOf(token, nonce) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(token), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(nonce)));
}

// Asks one port who answers. A real Sahl says so; with our token it also proves it holds the same one (an HMAC of a nonce only
// we chose), so the token and the page's details only go to the Sahl this browser was paired with.
async function probe(port, token) {
  const nonce = hex(crypto.getRandomValues(new Uint8Array(16)));
  try {
    const r = await fetch(`http://127.0.0.1:${port}/health?nonce=${nonce}`, { signal: AbortSignal.timeout(PROBE_MS) });
    const data = await r.json();
    if (!r.ok || data?.app !== "Sahl") return null;
    // the proof covers the port we asked, so a program on another port can't relay Sahl's answer as its own
    const verified = Boolean(token) && typeof data.proof === "string" && data.proof === (await proofOf(token, `${nonce}:${port}`));
    return { port, base: `http://127.0.0.1:${port}`, data, verified };
  } catch {
    return null;
  }
}

const servers = async (token) => (await Promise.all(PORTS.map((p) => probe(p, token)))).filter(Boolean);
let lastPort = 0; // the port that answered last, tried first

const closed = () => new BridgeError("Sahl isn't running, or its browser bridge is blocked. Open Sahl and try again.", "closed");

async function request(base, path, body, token) {
  let r;
  try {
    r = await fetch(base + path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "content-type": "application/json", ...(token ? { "x-sahl-ext-token": token } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw closed();
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new BridgeError(data.detail || `Sahl returned ${r.status}`, r.status === 403 ? "pair" : "");
  return data;
}

// a call with our token: only to the Sahl that proves it holds that token, wherever in the range it started
async function call(path, body, token) {
  let hit = lastPort ? await probe(lastPort, token) : null;
  if (!hit?.verified) {
    const found = await servers(token);
    hit = found.find((h) => h.verified);
    if (!hit) throw found.length ? new BridgeError("Sahl doesn't know this browser. Pair it again.", "pair") : closed();
  }
  lastPort = hit.port;
  return request(hit.base, path, body, token);
}

async function storedToken() {
  const { token } = await chrome.storage.local.get("token");
  return token || "";
}

// A box in a frame other than the page's own is named "<frame>:<id>", so ids stay unique across the tab's frames.
const named = (frame, v) => Array.isArray(v) ? v.map((x) => named(frame, x))
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) =>
    [k, k === "element_id" && typeof x === "string" && frame ? `${frame}:${x}` : named(frame, x)])) : v;
const bare = (v) => Array.isArray(v) ? v.map(bare)
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) =>
    [k, k === "element_id" && typeof x === "string" ? x.replace(/^\d+:/, "") : bare(x)])) : v;
const frameOf = (id) => Number(/^(\d+):/.exec(String(id))?.[1] || 0);

// the page and every frame we may read (a frame we have no access to is left out); the page itself is frame 0
async function inject(tabId) {
  try {
    const out = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ["content.js"] });
    return [...new Set(out.map((r) => r.frameId))].sort((a, b) => a - b);
  } catch {
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
      return [0];
    } catch {
      throw new BridgeError("This page can't be read. Open a normal web page, not a browser settings page.", "tab");
    }
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
  const frames = await inject(tabId);
  const pages = [];
  for (const frameId of frames) {
    try {
      const page = await chrome.tabs.sendMessage(tabId, { type: `sahl:v${VERSION}:scan`, strings }, { frameId });
      if (page && (frameId === 0 || page.fields?.length)) pages.push({ frameId, page });
    } catch {
      if (frameId === 0) {
        await endReading(tabId);
        throw new BridgeError("Couldn't read this page. Reload it and try again.", "tab");
      }
    }
  }
  if (!pages.length) {
    await endReading(tabId);
    throw new BridgeError("This page has no form Sahl can read.", "empty");
  }
  // the page's own address, title and headings stand for the tab; frames add their boxes (listed after the page's own)
  const top = (pages.find((p) => p.frameId === 0) || pages[0]).page;
  const merged = {
    url: top.url, title: top.title, headings: top.headings,
    fields: pages.flatMap(({ frameId, page }, i) => named(frameId, page.fields || []).map((f) =>
      i && Array.isArray(f.rect) ? { ...f, rect: [f.rect[0], f.rect[1] + 100000 * i, ...f.rect.slice(2)] } : f)),
  };
  let plan;
  try {
    plan = await call("/page", { ...metadata(merged), person: person || null }, token);
  } catch (e) {
    await endReading(tabId);
    throw e;
  }
  const fields = plan.fields || [];
  const asked = fields.filter((f) => f.unknown && !f.told).length;
  let first = 0; // the page's boxes are numbered first, then each frame's, as the popup lists them
  for (const { frameId } of pages) {
    const mine = fields.filter((f) => frameOf(f.element_id) === frameId);
    try {
      await chrome.tabs.sendMessage(tabId, {
        type: `sahl:v${VERSION}:render`, fields: bare(mine), asked, first, strings,
      }, { frameId });
    } catch {
      if (frameId === 0) await endReading(tabId);
    }
    first += mine.filter((f) => f.unknown && !f.told).length;
  }
  return plan;
}

async function fill(tabId, ids, person, replace) {
  const token = await storedToken();
  if (!token) throw new BridgeError("Pair with Sahl first.", "pair");
  const released = await call("/values", { element_ids: ids, person: person || null }, token);
  const byFrame = new Map();
  for (const v of released.values || []) {
    const frame = frameOf(v.element_id);
    byFrame.set(frame, [...(byFrame.get(frame) || []), v]);
  }
  const results = [];
  for (const [frameId, values] of byFrame) {
    try {
      const done = await chrome.tabs.sendMessage(tabId, { type: `sahl:v${VERSION}:fill`, values: bare(values), replace: Boolean(replace) }, { frameId });
      results.push(...named(frameId, done || []));
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

// who answers, in whichever port of the range Sahl took; verified: it holds the token this browser was paired with
async function health() {
  const found = await servers(await storedToken());
  if (!found.length) return { error: closed().message, code: "closed" };
  const hit = found.find((h) => h.verified) || found[0];
  lastPort = hit.port;
  return { ...hit.data, verified: hit.verified };
}

// the code's last digit names the port of the Sahl that showed it; the code goes there and nowhere else
async function pair(code) {
  code = String(code || "").trim();
  if (!/^\d{6}$/.test(code)) throw new BridgeError("A pairing code is 6 digits.", "pair");
  const hit = await probe(PORTS[0] + Number(code.slice(-1)), "");
  if (!hit) throw closed();
  const out = await request(hit.base, "/pair", { code, name: "Sahl browser" });
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

