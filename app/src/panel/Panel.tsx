import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { emitTo, listen } from "@tauri-apps/api/event";
import { getCurrentWindow, LogicalPosition, LogicalSize } from "@tauri-apps/api/window";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { ask, open } from "@tauri-apps/plugin-dialog";
import { api, ApiError, type Guide, type Lang, type Person, type Reading } from "../api";
import strings from "./i18n.json";
import "./panel.css";

const LANGS: { id: Lang; name: string }[] = [
  { id: "en", name: "English" },
  { id: "ar", name: "العربية" },
  { id: "ur", name: "اردو" },
  { id: "ml", name: "മലയാളം" },
];
const RTL = new Set<Lang>(["ar", "ur"]);
const SHORTCUT = navigator.userAgent.includes("Mac") ? "⌥ Space" : "Alt+Space";
type Key = keyof typeof strings.en;

/** `/Users/me/...` or `C:\Users\me\...` → `~/...` */
function prettyPath(p: string) {
  return p.replace(/^\/Users\/[^/]+/, "~").replace(/^[A-Za-z]:\\Users\\[^\\]+/, "~");
}

function saved<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, v: string) {
  try {
    localStorage.setItem(key, v);
  } catch {}
}

export default function Panel() {
  const [lang, setLang] = useState<Lang>(() => saved("lang", "en"));
  const [mode, setMode] = useState<"show" | "fill">(() => saved("mode", "show"));
  const [guides, setGuides] = useState<Guide[] | null>(null);
  const [guide, setGuide] = useState("medical-fitness");
  const [people, setPeople] = useState<Person[]>([]);
  const [library, setLibrary] = useState<string | null>(null);
  const [person, setPerson] = useState<string>(() => saved("person", ""));
  const [reading, setReading] = useState<Reading | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Key | string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const t = (k: Key, vars: Record<string, string | number> = {}) =>
    Object.entries(vars).reduce((s, [a, b]) => s.replace(`{${a}}`, String(b)), strings[lang][k] ?? strings.en[k]);

  useEffect(() => {
    api<Guide[]>("/guides").then(setGuides).catch((e) => setError(String(e.message)));
    api<Person[]>("/people").then(setPeople).catch(() => {});
    api<{ path: string }>("/library").then((r) => setLibrary(r.path)).catch(() => {});
  }, []);

  const fail = (e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    if (e instanceof ApiError && e.status === 0) return setError("restarted");
    setError(e instanceof ApiError && e.status === 409 ? (msg.startsWith("typing") ? "err_type" : "err_screen") : msg);
  };

  const read = useCallback(async () => {
    setBusy(true);
    setError(null);
    setCopied(false);
    const overlay = await WebviewWindow.getByLabel("overlay");
    try {
      await overlay?.hide(); // never read our own ring
      await new Promise((r) => setTimeout(r, 120));
      const win = getCurrentWindow();
      const [pos, size, scale] = await Promise.all([win.outerPosition(), win.outerSize(), win.scaleFactor()]);
      const panel = [pos.x / scale, pos.y / scale, (pos.x + size.width) / scale, (pos.y + size.height) / scale];
      const r = await api<Reading>("/read", { guide, person: person || null, exclude: [panel] });
      setReading(r);
      setPeople(r.people);
      const next = r.fields.find((f) => f.id === r.next);
      if (next && r.monitor && overlay) {
        const [mx, my, mw, mh] = r.monitor; // cover the monitor the form is on
        await overlay.setPosition(new LogicalPosition(mx, my));
        await overlay.setSize(new LogicalSize(mw, mh));
      }
      await emitTo("overlay", "ring", next ? { box: next.input_box, label: next.label, origin: r.monitor!.slice(0, 2) } : null);
      if (next) await overlay?.show();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [guide, person]);

  useEffect(() => {
    const un = listen("read", () => void read());
    return () => void un.then((f) => f());
  }, [read]);

  const act = async (path: "/fill" | "/confirm", fieldId: string) => {
    setBusy(true);
    try {
      const r = await api<{ landed?: boolean }>(path, { field_id: fieldId });
      await read();
      if (r.landed === false) setError("missed"); // after read(), which clears errors
    } catch (e) {
      fail(e);
      setBusy(false);
    }
  };

  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const importPaths = async (paths: string[]) => {
    setBusy(true);
    setError(null);
    const poll = setInterval(() => api<{ done: number; total: number }>("/vault/progress").then(setProgress).catch(() => {}), 700);
    try {
      const names = new Set<string>();
      const skipped: string[] = [];
      let aiOn = true;
      for (const path of paths) {
        const r = await api<{ people: string[]; skipped: string[]; ai: boolean }>("/vault/import", { path });
        r.people.forEach((n) => names.add(n));
        skipped.push(...r.skipped);
        aiOn &&= r.ai;
      }
      const notes = [names.size ? t("people_found", { names: [...names].join(", ") }) : t("nothing_found")];
      if (skipped.length) notes.push(t("skipped", { files: skipped.join(", ") }));
      if (!aiOn) notes.push(t("no_ai"));
      setNote(notes.join(" "));
      setPeople(await api<Person[]>("/people"));
      if (reading) await read();
    } catch (e) {
      fail(e);
    } finally {
      clearInterval(poll);
      setProgress(null);
      setBusy(false);
    }
  };

  const addDoc = async () => {
    const picked = await open({ multiple: true, filters: [{ name: "Document", extensions: ["pdf", "png", "jpg", "jpeg"] }] });
    if (picked?.length) await importPaths(picked);
  };

  // drop a folder or document images anywhere on the panel
  const [dropping, setDropping] = useState(false);
  const importRef = useRef(importPaths);
  importRef.current = importPaths;
  useEffect(() => {
    const un = getCurrentWebview().onDragDropEvent((e) => {
      if (e.payload.type === "enter" || e.payload.type === "over") setDropping(true);
      else {
        setDropping(false);
        if (e.payload.type === "drop" && e.payload.paths.length) void importRef.current(e.payload.paths);
      }
    });
    return () => void un.then((f) => f());
  }, []);

  const changeLibrary = async () => {
    const dir = await open({ directory: true, multiple: false });
    if (!dir) return;
    setBusy(true);
    try {
      const r = await api<{ path: string; people: string[] }>("/library", { path: dir });
      setLibrary(r.path);
      setPeople(await api<Person[]>("/people"));
      setNote(r.people.length ? t("people_found", { names: r.people.join(", ") }) : t("nothing_found"));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const forget = async () => {
    if (!(await ask(t("forget_ask"), { kind: "warning" }))) return;
    await api("/vault/forget", {}).catch(fail);
    setNote(null);
    setPeople([]);
    if (reading) await read();
  };

  const field = reading?.fields.find((f) => f.id === reading.next) ?? null;
  const index = field ? reading!.fields.indexOf(field) + 1 : 0;
  const canFill = mode === "fill" && field?.input === "text" && field.vault?.verified;

  return (
    <div className={dropping ? "panel dropping" : "panel"} dir={RTL.has(lang) ? "rtl" : "ltr"} lang={lang}>
      {dropping && <div className="drop">{t("drop_here")}</div>}
      <header data-tauri-drag-region>
        <img src="/logo.png" alt="Sahl" className="logo" data-tauri-drag-region />
        <span className="status" data-tauri-drag-region>
          <i className="dot" /> {t("local")}
        </span>
      </header>

      <div className="seg" role="radiogroup" aria-label="Language">
        {LANGS.map((l) => (
          <button key={l.id} role="radio" aria-checked={lang === l.id} lang={l.id}
            onClick={() => (setLang(l.id), save("lang", l.id))}>
            {l.name}
          </button>
        ))}
      </div>

      <div className="row">
        <select value={guide} onChange={(e) => (setGuide(e.target.value), setReading(null))} aria-label="Form">
          {(guides ?? []).map((g) => (
            <option key={g.id} value={g.id}>{g.service[lang]}</option>
          ))}
        </select>
      </div>

      {people.length > 1 && (
        <label className="row person">
          <span>{t("filling_for")}</span>
          <select value={reading?.person ?? person} onChange={(e) => (setPerson(e.target.value), save("person", e.target.value))}>
            {!(reading?.person ?? person) && <option value="">{t("choose_person")}</option>}
            {people.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
      )}

      <div className="seg small" role="radiogroup" aria-label="Mode">
        {(["show", "fill"] as const).map((m) => (
          <button key={m} role="radio" aria-checked={mode === m} onClick={() => (setMode(m), save("mode", m))}>
            {t(m === "show" ? "show_only" : "confirm_fill")}
          </button>
        ))}
      </div>

      <button className="primary" disabled={busy || !guides} onClick={read}>
        {!guides ? t("starting") : busy ? t("reading") : t("read")} <kbd>{SHORTCUT}</kbd>
      </button>

      {error && <p className="error" role="alert">{error in strings.en ? t(error as Key) : error}</p>}

      {reading && !field && !error && (
        <p className="quiet">{reading.fields.length ? t("all_done") : t("no_form")}</p>
      )}

      {reading && !reading.person && people.length > 1 && <p className="warn">{t("who")}</p>}

      {field && (reading!.person || people.length < 2) && (
        <section className="card" aria-live="polite">
          <div className="eyebrow">
            {t("next_box")} · {t("step", { n: index, total: reading!.fields.length })}
          </div>
          <h2 dir="auto">{field.label}</h2>
          <p className="help">{field.help[lang]}</p>

          {field.vault ? (
            <>
              <div className="value">
                <code dir="ltr">{field.vault.value}</code>
                <button className="ghost" onClick={() => {
                  navigator.clipboard.writeText(field.vault!.value);
                  setCopied(true);
                }}>{copied ? t("copied") : t("copy")}</button>
              </div>
              {field.vault.crop && (
                <figure>
                  <img src={field.vault.crop} alt="" />
                  <figcaption>{t("from", { source: field.vault.source })}</figcaption>
                </figure>
              )}
              {!field.vault.verified && <p className="warn">{t("unverified")}</p>}
            </>
          ) : (
            <p className="quiet">{field.input === "text" ? t("not_in_vault") : t("you_choose")}</p>
          )}

          <div className="actions">
            {canFill ? (
              <button className="primary" disabled={busy} onClick={() => act("/fill", field.id)}>{t("yes_fill")}</button>
            ) : (
              <button className="primary" disabled={busy} onClick={() => act("/confirm", field.id)}>{t("done_next")}</button>
            )}
            <button className="ghost" disabled={busy} onClick={() => act("/confirm", field.id)}>{t("skip")}</button>
          </div>
        </section>
      )}

      <footer>
        <div className="docs">
          <span>{t("documents")}</span>
          <button className="ghost" disabled={busy || !guides} onClick={addDoc}>{t("add_doc")}</button>
          <button className="ghost danger" disabled={busy || !guides} onClick={forget}>{t("forget")}</button>
        </div>
        {library && (
          <div className="library">
            <span dir="ltr" title={library}>{prettyPath(library)}</span>
            <button className="ghost" disabled={busy || !guides} onClick={changeLibrary}>{t("change")}</button>
          </div>
        )}
        {progress && progress.total > 0 && (
          <p className="quiet" aria-live="polite">{t("importing", { done: progress.done, total: progress.total })}</p>
        )}
        {note && !progress && <p className="quiet">{note}</p>}
        <p className="fine">{t("never_submits")}</p>
      </footer>
    </div>
  );
}
