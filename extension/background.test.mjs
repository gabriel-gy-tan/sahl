// node --test extension/   Loads background.js with a fake chrome and fetch to check how it finds and trusts a bridge.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const TOKEN = "t".repeat(32);
function load(servers, token) {
  const fetch = async (url) => {
    const u = new URL(url);
    const s = servers[u.port];
    if (!s) throw new Error("refused");
    const nonce = u.searchParams.get("nonce");
    const body = { app: s.app ?? "Sahl", port: Number(u.port), lang: "en" };
    if (nonce && s.token) body.proof = createHmac("sha256", s.token).update(`${nonce}:${s.as ?? u.port}`).digest("hex");
    return { ok: true, json: async () => body };
  };
  const ctx = {
    fetch, console, crypto: globalThis.crypto, TextEncoder, AbortSignal, URL,
    chrome: { storage: { local: { get: async () => (token ? { token } : {}), set: async () => {} } },
      runtime: { onMessage: { addListener() {} } }, scripting: {}, tabs: {} },
  };
  vm.createContext(ctx);
  vm.runInContext(readFileSync(new URL("./background.js", import.meta.url), "utf8"), ctx);
  return ctx;
}

test("finds Sahl on a later port and verifies it holds our token", async () => {
  const c = load({ 8767: { token: TOKEN } }, TOKEN);
  const h = await c.health();
  assert.equal(h.port, 8767);
  assert.equal(h.verified, true);
});

test("a Sahl with another token is found but not verified", async () => {
  const c = load({ 8765: { token: "x".repeat(32) } }, TOKEN);
  const h = await c.health();
  assert.equal(h.verified, false);
});

test("something else on a port is ignored; nothing at all reports closed", async () => {
  assert.equal((await load({ 8765: { app: "Other" } }, TOKEN).health()).code, "closed");
  assert.equal((await load({}, TOKEN).health()).code, "closed");
});

test("element ids are qualified per frame and unqualified for the page", async () => {
  const c = vm.runInContext("({ named, bare, frameOf })", load({}, TOKEN)); // const bindings aren't on the context object
  const f = c.named(3, [{ element_id: "e1", parts: [{ element_id: "e2" }] }]);
  assert.equal(f[0].element_id, "3:e1");
  assert.equal(f[0].parts[0].element_id, "3:e2");
  assert.equal(c.bare(f)[0].element_id, "e1");
  assert.equal(c.frameOf("3:e1"), 3);
  assert.equal(c.frameOf("e1"), 0);
});

test("a proof relayed from another port is not trusted", async () => {
  // a program on 8765 passes on the answer of the real Sahl on 8766: the proof names 8766, so 8765 isn't verified
  const c = load({ 8765: { token: TOKEN, as: 8766 } }, TOKEN);
  const h = await c.health();
  assert.equal(h.verified, false);
});
