import { invoke } from "@tauri-apps/api/core";

export type Box = [number, number, number, number];
export type Lang = "en" | "ar" | "ur" | "ml";
export type Field = {
  id: string;
  label: string;
  label_box: Box;
  input_box: Box;
  input: "text" | "date" | "select";
  help: Record<Lang, string>;
  vault: { value: string; verified: boolean; source: string; crop: string | null } | null;
  confirmed: boolean;
};
export type Person = { id: string; name: string };
export type Reading = { fields: Field[]; next: string | null; monitor: Box | null; person: string | null; people: Person[] };
export type Guide = { id: string; service: Record<Lang, string> };
export type Reply = { reply: string; kind: "match" | "new" | "unsure"; guide: string | null; name: string };

let base: { url: string; token: string } | null = null;

async function connect() {
  while (!base) {
    const info = await invoke<{ port: number | null; token: string }>("sidecar_info");
    if (info.port) base = { url: `http://127.0.0.1:${info.port}`, token: info.token };
    else await new Promise((r) => setTimeout(r, 300));
  }
  return base;
}

// safe to send again if the sidecar died mid-call; /fill and /vault/import are not
const RETRY = new Set(["/guides", "/read", "/chat"]);

/** Calls the local sidecar. Waits for it to come up, and for a restarted one to come back. */
export async function api<T>(path: string, body?: unknown): Promise<T> {
  for (let i = 0; ; i++) {
    const b = await connect();
    try {
      const r = await fetch(b.url + path, {
        method: body === undefined ? "GET" : "POST",
        headers: { "x-sahl-token": b.token, "content-type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!r.ok) throw new ApiError(r.status, (await r.json().catch(() => ({}))).detail ?? r.statusText);
      return r.json();
    } catch (e) {
      if (e instanceof ApiError) throw e;
      base = null; // a restarted sidecar listens on a new port
      if (!RETRY.has(path) || i > 100) throw new ApiError(0, "restarted");
      await new Promise((r) => setTimeout(r, 300));
    }
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}
