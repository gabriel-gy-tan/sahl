import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { emitTo, listen } from "@tauri-apps/api/event";
import { getCurrentWindow, LogicalPosition, LogicalSize } from "@tauri-apps/api/window";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { ask, open } from "@tauri-apps/plugin-dialog";
import { api, ApiError, type Guide, type Lang, type Person, type Reading, type Reply } from "../api";
import strings from "./i18n.json";
import "./panel.css";

const LANGS: { id: Lang; name: string }[] = [
  { id: "en", name: "English" },
  { id: "ar", name: "العربية" },
  { id: "ur", name: "اردو" },
  { id: "ml", name: "മലയാളം" },
];
const RTL = new Set<Lang>(["ar", "ur"]);
// the read-the-form shortcut (SHORTCUT in lib.rs): Alt+Space is the window menu on Windows
const KEY = navigator.userAgent.includes("Mac") ? "⌥ Space" : "Ctrl Alt Space";
const GENERIC = "any-form"; // the guide for forms Sahl has no guide for
const WIDTH = 600; // the island when open, at normal text size
const EAR = 12; // the concave corners that join the island to the top of the screen
const WING = 34; // folded, the island reaches this far past each side of the notch, to show the palm beside it
type Key = keyof typeof strings.en;
type Notch = { real: boolean; width: number; height: number };

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

function greeting(): Key {
  const h = new Date().getHours();
  if (Math.random() < 0.3) return Math.random() < 0.5 ? "greet_hey" : "greet_again";
  return h < 5 || h >= 22 ? "greet_late" : h < 12 ? "greet_morning" : h < 17 ? "greet_afternoon" : "greet_evening";
}

/** One message in the "what form?" conversation. Sahl's messages may carry an offer: a guide, a form it has no guide for
 * ("new"), the list to choose from ("pick"), or "interpret" (on to the generic guide). */
type Said = { role: "user" | "assistant"; text: string; kind?: Reply["kind"] | "pick" | "interpret"; guide?: string | null; name?: string };

type Option = { value: string; label: string; quiet?: boolean }; // quiet: a way out, like "Other"

/** A dropdown that opens inside the island, so it grows with it instead of popping a native menu over it. */
function Dropdown({ value, options, placeholder, label, onChange }: {
  value: string; options: Option[]; placeholder: string; label: string; onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.value === value);
  return (
    <div className={open ? "dropdown open" : "dropdown"}
      onKeyDown={(e) => e.key === "Escape" && open && (e.stopPropagation(), setOpen(false))}>
      <button type="button" className="dropdown-button" aria-haspopup="listbox" aria-expanded={open} aria-label={label}
        onClick={() => setOpen(!open)}>
        <span className={current ? undefined : "placeholder"}>{current?.label ?? placeholder}</span>
        <span className="chevron" aria-hidden />
      </button>
      {open && (
        <div className="dropdown-list" role="listbox" aria-label={label}>
          {options.map((o, i) => (
            <button type="button" role="option" key={o.value} aria-selected={o.value === value} autoFocus={i === 0}
              className={o.quiet ? "quiet" : undefined}
              onClick={() => (setOpen(false), onChange(o.value))}>
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const TEXT_SIZES = ["1", "1.15", "1.3"] as const;

/** Reads text aloud with the computer's own voices (on the device). The voice follows the text's script. */
function speak(text: string) {
  if (!("speechSynthesis" in window) || !text.trim()) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = /[\u0d00-\u0d7f]/.test(text) ? "ml-IN" : /[ٹڈڑںےۓہھ]/.test(text) ? "ur-PK" : /[\u0600-\u06ff]/.test(text) ? "ar-SA" : "en-US";
  speechSynthesis.cancel(); // one voice at a time
  speechSynthesis.speak(u);
}

function Speaker({ text, label }: { text: string; label: string }) {
  return (
    <button type="button" className="speaker" aria-label={label} title={label} onClick={() => speak(text)}>
      <svg viewBox="0 0 24 24" aria-hidden><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" /><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" /></svg>
    </button>
  );
}

function Palm({ leaving = false }: { leaving?: boolean }) {
  return (
    <picture className={leaving ? "palm leaving" : "palm"}>
      <source srcSet="/palm.png" media="(prefers-reduced-motion: reduce)" />
      <img src="/palm-wave.gif" alt="" />
    </picture>
  );
}

export default function Panel() {
  const [lang, setLang] = useState<Lang>(() => saved("lang", "en"));
  const [mode, setMode] = useState<"show" | "fill">(() => saved("mode", "show"));
  const [textSize, setTextSize] = useState<(typeof TEXT_SIZES)[number]>(() => saved("text", "1"));
  const [readAloud, setReadAloud] = useState<"on" | "off">(() => saved("speak", "off"));
  const openW = Math.round(WIDTH * (1 + (Number(textSize) - 1) * 0.6)); // bigger text gets a wider island too
  const [guides, setGuides] = useState<Guide[] | null>(null);
  const [guide, setGuide] = useState<string | null>(null);
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

  // --- the island: boot palm, then open / folded into the notch ---
  const [notch, setNotch] = useState<Notch>({ real: true, width: 200, height: 32 });
  const [phase, setPhase] = useState<"boot" | "leaving" | "ready">("boot");
  const [isOpen, setOpen] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [contentH, setContentH] = useState(0);
  const contentRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    invoke<Notch>("notch").then(setNotch).catch(() => {});
    // the folded island moved to another screen (its top centre was reached): take that screen's notch, or tab
    const un = listen<Notch>("notch", (e) => setNotch(e.payload));
    return () => void un.then((f) => f());
  }, []);

  useEffect(() => {
    if (guides && phase === "boot") setPhase("leaving"); // the palm goes up into the notch, then the island opens
    if (phase !== "leaving") return;
    const id = setTimeout(() => (setPhase("ready"), setOpen(true)), 380);
    return () => clearTimeout(id);
  }, [guides, phase]);

  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setContentH(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const failedBoot = !guides && !!error;
  const shownOpen = (phase === "ready" && isOpen) || failedBoot;
  const size = phase !== "ready" && !failedBoot
    ? { w: Math.max(notch.width, 300), h: notch.height + 128 }
    : shownOpen
      ? { w: openW, h: contentH } // the content's padding already clears the notch
      : { w: notch.width + 2 * WING, h: notch.height }; // folded: the still palm beside the notch says Sahl is running

  // the window is always the open width (only its height changes, see `island` in lib.rs); it grows at once and
  // shrinks after the animation, so the island never gets clipped
  const shownH = useRef(0);
  useEffect(() => {
    const place = (h: number) =>
      invoke("island", { width: openW + 2 * EAR, height: h, islandWidth: size.w, islandHeight: size.h, open: shownOpen }).catch(() => {});
    shownH.current = Math.max(size.h, shownH.current);
    place(shownH.current);
    const id = setTimeout(() => place((shownH.current = size.h)), 560);
    return () => clearTimeout(id);
  }, [size.w, size.h, shownOpen, openW, notch]); // notch: a new screen re-places the window there

  // --- what form? ---
  const [text, setText] = useState("");
  const [thread, setThread] = useState<Said[]>([]);
  const [thinking, setThinking] = useState(false);
  const [formName, setFormName] = useState(""); // for a form Sahl has no guide for, in their words
  const [focused, setFocused] = useState(false);
  const [hello, setHello] = useState<Key>(greeting);
  const inputRef = useRef<HTMLInputElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const known = (guides ?? []).filter((g) => g.id !== GENERIC);
  const guideLabel = (id: string | null | undefined) => known.find((g) => g.id === id)?.service[lang] ?? "";

  const choose = (id: string, name = "") => {
    setGuide(id);
    setFormName(name);
    setReading(null);
    setError(null);
  };
  const say = (m: Said) => setThread((th) => [...th, m]);
  const send = async (typed: string) => {
    const words = typed.trim();
    if (!words || thinking) return;
    const next = [...thread, { role: "user" as const, text: words }];
    setThread(next);
    setText("");
    setThinking(true);
    setError(null);
    try {
      // the greeting goes first so the model knows what it asked
      const messages = [{ role: "assistant", text: `${t(hello)} ${t("ask_form")}` }, ...next.map((m) => ({ role: m.role, text: m.text }))];
      const r = await api<Reply>("/chat", { messages });
      say({ role: "assistant", text: r.reply, kind: r.reply || r.kind !== "unsure" ? r.kind : "pick", guide: r.guide, name: r.name });
    } catch (e) {
      fail(e);
    } finally {
      setThinking(false);
    }
  };
  // starting points for a fresh conversation, built from the guides Sahl has
  const suggestions = [
    t("suggest_help"),
    ...known.slice(0, 2).flatMap((g) => {
      const form = g.service[lang].split("·")[0].trim();
      return [t("suggest_fill", { form }), t("suggest_about", { form })];
    }),
  ].slice(0, 3);
  const other = () => say({ role: "assistant", text: t("interpret"), kind: "interpret" });
  useEffect(() => {
    const last = thread[thread.length - 1];
    if (last?.kind !== "interpret") return;
    const id = setTimeout(() => choose(GENERIC), 1400); // "Sure, I'll interpret it as we go along", then on to the form
    return () => clearTimeout(id);
  }, [thread]);
  useEffect(() => {
    const last = thread[thread.length - 1];
    if (readAloud === "on" && last?.role === "assistant") speak(last.text || (last.kind === "match" ? t("sounds_like") : last.kind === "pick" ? t("not_sure") : ""));
  }, [thread]); // only when a message arrives
  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [thread, thinking]);
  const restart = () => { // back to the conversation, which is kept
    setGuide(null);
    setReading(null);
    setError(null);
    void emitTo("overlay", "ring", null);
    void WebviewWindow.getByLabel("overlay").then((o) => o?.hide());
  };

  const read = useCallback(async () => {
    if (!guide) return;
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
    const un = listen("read", () => (setOpen(true), void read()));
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
  const [readingDocs, setReadingDocs] = useState(false);
  const importPaths = async (paths: string[]) => {
    setBusy(true);
    setReadingDocs(true);
    setOpen(true);
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
      setReadingDocs(false);
      setBusy(false);
    }
  };

  const addDoc = async () => {
    const picked = await open({ multiple: true, filters: [{ name: "Document", extensions: ["pdf", "png", "jpg", "jpeg"] }] });
    if (picked?.length) await importPaths(picked);
  };

  // drop a folder or document images anywhere on the island
  const [dropping, setDropping] = useState(false);
  const importRef = useRef(importPaths);
  importRef.current = importPaths;
  useEffect(() => {
    const un = getCurrentWebview().onDragDropEvent((e) => {
      if (e.payload.type === "enter" || e.payload.type === "over") setDropping(true), setOpen(true);
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
    setReadingDocs(true);
    try {
      const r = await api<{ path: string; people: string[] }>("/library", { path: dir });
      setLibrary(r.path);
      setPeople(await api<Person[]>("/people"));
      setNote(r.people.length ? t("people_found", { names: r.people.join(", ") }) : t("nothing_found"));
    } catch (e) {
      fail(e);
    } finally {
      setReadingDocs(false);
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
  const guideName = guides?.find((g) => g.id === guide)?.service[lang];

  // --- open on hover, fold back into the notch a moment after the pointer leaves ---
  const keep = busy || thinking || sheet || readingDocs || dropping || !!field || focused;
  const keepRef = useRef(keep);
  keepRef.current = keep;
  const hovered = useRef(false);
  const fold = useRef<ReturnType<typeof setTimeout>>(undefined);
  const foldSoon = useCallback((ms: number) => {
    clearTimeout(fold.current);
    fold.current = setTimeout(() => {
      if (!hovered.current && !keepRef.current) setOpen(false), setSheet(false);
    }, ms);
  }, []);
  useEffect(() => {
    const un = listen<boolean>("hover", (e) => {
      hovered.current = e.payload;
      if (e.payload) clearTimeout(fold.current), setOpen(true);
      else foldSoon(500);
    });
    return () => void un.then((f) => f());
  }, [foldSoon]);
  useEffect(() => {
    if (phase === "ready" && isOpen && !keep) foldSoon(hovered.current ? 500 : 5000); // after boot, stay a while for a first look
  }, [phase, isOpen, keep, foldSoon]);
  useEffect(() => {
    if (isOpen) setHello(greeting());
    else inputRef.current?.blur();
  }, [isOpen]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && (setOpen(false), setSheet(false));
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);

  return (
    <div className="stage" dir={RTL.has(lang) ? "rtl" : "ltr"} lang={lang} style={{ ["--text" as string]: textSize }}>
      <div className={`island${shownOpen ? " open" : ""}${notch.real ? "" : " virtual"}`}
        style={{ width: size.w, height: size.h, ["--notch" as string]: `${notch.height}px`, ["--open-w" as string]: `${openW}px`,
          // the glow also traces a real notch; on a screen without one these are 0 and it only rounds the island
          ["--nw" as string]: `${notch.real ? notch.width : 0}px`, ["--nh" as string]: `${notch.real ? notch.height : 0}px` }}>
        <div className={phase !== "ready" || thinking ? "glow on" : "glow"} aria-hidden />
        <div className="clip">
          {phase !== "ready" && !failedBoot && <div className="boot"><Palm leaving={phase === "leaving"} /></div>}
          {phase === "ready" && <img className="mini" src="/palm-mini.png" alt="" style={{ width: WING }} />}

          <div className="content" ref={contentRef} inert={!shownOpen}>
            {dropping && <div className="drop">{t("drop_here")}</div>}
            <button className={sheet ? "more open" : "more"} aria-label={sheet ? t("close") : t("settings")} aria-expanded={sheet}
              onClick={() => setSheet(!sheet)}>
              <i /><i /><i />
            </button>

            {sheet ? (
              <div className="sheet">
                {/* the title shares its row with the close button, so nothing runs under it */}
                <h2 className="sheet-title">{t("settings")}</h2>

                <section className="group" aria-label={t("display")}>
                  <div className="row stacked">
                    <span>{t("language")}</span>
                    <div className="seg" role="radiogroup" aria-label={t("language")}>
                      {LANGS.map((l) => (
                        <button key={l.id} role="radio" aria-checked={lang === l.id} lang={l.id}
                          onClick={() => (setLang(l.id), save("lang", l.id))}>
                          {l.name}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="row">
                    <span>{t("text_size")}</span>
                    <div className="seg compact" role="radiogroup" aria-label={t("text_size")}>
                      {TEXT_SIZES.map((z, i) => (
                        <button key={z} role="radio" aria-checked={textSize === z} aria-label={`${t("text_size")} ${i + 1}`}
                          onClick={() => (setTextSize(z), save("text", z))} style={{ fontSize: `${12 + i * 3}px` }}>A</button>
                      ))}
                    </div>
                  </div>
                  <div className="row">
                    <span>{t("read_aloud")}</span>
                    <button role="switch" className="switch" aria-checked={readAloud === "on"} aria-label={t("read_aloud")}
                      onClick={() => { const v = readAloud === "on" ? "off" : "on"; setReadAloud(v); save("speak", v); }}>
                      <i />
                    </button>
                  </div>
                </section>

                <section className="group" aria-label={t("fill_mode")}>
                  <div className="row stacked">
                    <span>{t("fill_mode")}</span>
                    <div className="seg" role="radiogroup" aria-label={t("fill_mode")}>
                      {(["show", "fill"] as const).map((m) => (
                        <button key={m} role="radio" aria-checked={mode === m} onClick={() => (setMode(m), save("mode", m))}>
                          {t(m === "show" ? "show_only" : "confirm_fill")}
                        </button>
                      ))}
                    </div>
                  </div>
                  {people.length > 1 && (
                    <div className="row stacked">
                      <span>{t("filling_for")}</span>
                      <Dropdown value={reading?.person ?? person} label={t("filling_for")} placeholder={t("choose_person")}
                        options={people.map((p) => ({ value: p.id, label: p.name }))}
                        onChange={(v) => (setPerson(v), save("person", v))} />
                    </div>
                  )}
                </section>

                <section className="group" aria-label={t("documents")}>
                  <div className="row">
                    <span>{t("documents")}</span>
                    <button className="ghost" disabled={busy || !guides} onClick={addDoc}>{t("add_doc")}</button>
                  </div>
                  {library && (
                    <div className="row">
                      <span className="path" dir="ltr" title={library}>{prettyPath(library)}</span>
                      <button className="ghost" disabled={busy || !guides} onClick={changeLibrary}>{t("change")}</button>
                    </div>
                  )}
                  <button className="row danger-row" disabled={busy || !guides} onClick={forget}>{t("forget")}</button>
                </section>

                {note && <p className="quiet">{note}</p>}
                <p className="fine">{t("local")} · {t("never_submits")}</p>
              </div>
            ) : readingDocs ? (
              <div className="busy" role="status" aria-live="polite">
                <Palm />
                <p>{progress?.total ? t("importing", { done: progress.done, total: progress.total }) : " "}</p>
              </div>
            ) : !guide ? (
              <div className="ask">
                <div className="thread" ref={threadRef} aria-live="polite">
                  {thread.length ? (
                    <div className="msg bot hello">
                      <img className="avatar" src="/palm-bold.png" alt="" />
                      <div className="said">
                        <h1 key={hello}>{t(hello)}</h1>
                        <p className="sub">{t("ask_form")}</p>
                      </div>
                    </div>
                  ) : ( // a fresh conversation: the greeting sits centred, like a new chat
                    <div className="hero">
                      <img src="/palm-bold.png" alt="" />
                      <h1 key={hello}>{t(hello)}</h1>
                      <p className="sub">{t("ask_form")}</p>
                    </div>
                  )}
                  {thread.map((m, i) => {
                    if (m.role === "user") return <div className="msg me" key={i}><p className="bubble" dir="auto">{m.text}</p></div>;
                    const last = i === thread.length - 1; // only the latest message keeps its buttons
                    return (
                      <div className="msg bot" key={i}>
                        <img className="avatar" src="/palm-bold.png" alt="" />
                        <div className="said">
                          {m.kind === "pick" ? <p>{t("not_sure")}</p> : m.kind === "new" ? <p>{t("interpret")}</p> : (
                            <p dir="auto">{m.text || (m.kind === "match" ? t("sounds_like") : "")}</p>
                          )}
                          {last && m.kind === "match" && m.guide && (
                            <button className="choice" onClick={() => choose(m.guide!)}>
                              <span>{guideLabel(m.guide)}</span><span aria-hidden>→</span>
                            </button>
                          )}
                          {last && m.kind === "new" && (
                            <button className="choice" onClick={() => choose(GENERIC, m.name)}>
                              <span dir="auto">{m.name}</span><span aria-hidden>→</span>
                            </button>
                          )}
                          {last && m.kind === "pick" && (
                            <Dropdown value="" label={t("not_sure")} placeholder={t("choose_form")}
                              options={[...known.map((g) => ({ value: g.id, label: g.service[lang] })), { value: GENERIC, label: t("other"), quiet: true }]}
                              onChange={(v) => (v === GENERIC ? other() : choose(v))} />
                          )}
                          {last && (m.kind === "unsure" || m.kind === "match") && (
                            <div className="note">
                              <div className="line">
                                {m.text && <Speaker text={m.text} label={t("listen")} />}
                                <button className="link" onClick={() => say({ role: "assistant", text: t("not_sure"), kind: "pick" })}>{t("pick_form")}</button>
                              </div>
                              {m.text && <p className="fine">{t("may_be_wrong")}</p>}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {(thinking || error) && (
                    <div className="msg bot">
                      <img className="avatar" src="/palm-bold.png" alt="" />
                      <div className="said">
                        {thinking ? (
                          <span className="typing" role="status" aria-label={t("thinking")}><i /><i /><i /></span>
                        ) : (
                          <p className="error" role="alert">{error && (error in strings.en ? t(error as Key) : error)}</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
                {!thread.length && !thinking && (
                  <div className="suggestions">
                    {suggestions.map((q) => <button key={q} type="button" dir="auto" onClick={() => send(q)}>{q}</button>)}
                  </div>
                )}
                <form className="composer" onSubmit={(e) => (e.preventDefault(), void send(text))}>
                  {/* empty, it follows the panel (right to left in Arabic and Urdu); typed, it follows the text */}
                  <input ref={inputRef} value={text} placeholder={t("placeholder")} dir={text ? "auto" : undefined} aria-label={t("ask_form")}
                    onChange={(e) => setText(e.target.value)}
                    onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} />
                  <button className="mic" type="button" aria-label={t("dictate")} title={t("dictate")}
                    onClick={() => (inputRef.current?.focus(), void invoke("dictate").catch(() => {}))}>
                    <svg viewBox="0 0 24 24" aria-hidden><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" /></svg>
                  </button>
                  <button className="send" type="submit" disabled={!text.trim() || thinking} aria-label={t("send")}>↑</button>
                </form>
              </div>
            ) : (
              <div className="work">
                <div className="line">
                  <span className="form-name">{guide === GENERIC ? formName || t("other") : guideName}</span>
                  <button className="link" onClick={restart}>{t("change")}</button>
                </div>

                {reading && !reading.person && people.length > 1 && (
                  <div className="stack">
                    <span className="warn">{t("who")}</span>
                    <Dropdown value={person} label={t("who")} placeholder={t("choose_person")}
                      options={people.map((p) => ({ value: p.id, label: p.name }))}
                      onChange={(v) => (setPerson(v), save("person", v))} />
                  </div>
                )}

                {field && (reading!.person || people.length < 2) ? (
                  <section className="card" aria-live="polite">
                    <div className="eyebrow">{t("next_box")} · {t("step", { n: index, total: reading!.fields.length })}</div>
                    <div className="line">
                      <h2 dir="auto">{field.label}</h2>
                      <Speaker text={`${field.label}. ${field.help[lang]}`} label={t("listen")} />
                    </div>
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
                ) : (
                  <>
                    {reading && !error && <p className="quiet">{reading.fields.length ? t("all_done") : t("no_form")}</p>}
                    <button className="primary" disabled={busy} onClick={read}>
                      {busy ? t("reading") : t("read")} <kbd>{KEY}</kbd>
                    </button>
                    {!reading && <p className="quiet">{t("open_form_hint", { key: KEY })}</p>}
                  </>
                )}
                {error && <p className="error" role="alert">{error in strings.en ? t(error as Key) : error}</p>}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
