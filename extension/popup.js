const $ = (id) => document.getElementById(id);
const status = (s) => ($("status").textContent = s);
const note = (s) => ($("note").textContent = s || "");
const KEY = navigator.platform.startsWith("Mac") ? "⌥ Space" : "Ctrl Alt Space"; // the app's read-the-form shortcut
let tabId = null;
let plan = null;
let busy = false;

// --- the panel's language (the bridge says which), from i18n.json; English when a string is missing ---
let STRINGS = { en: {} };
let lang = "en";
function T(key, vars = {}) {
  const s = STRINGS[lang]?.[key] ?? STRINGS.en[key] ?? key;
  return Object.entries(vars).reduce((out, [k, v]) => out.replaceAll(`{${k}}`, String(v)), s);
}
async function loadStrings() {
  try {
    STRINGS = await (await fetch(chrome.runtime.getURL("i18n.json"))).json();
  } catch {}
}
function useLanguage(l) {
  lang = STRINGS[l] ? l : "en";
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" || lang === "ur" ? "rtl" : "ltr";
  for (const el of document.querySelectorAll("[data-t]")) el.textContent = T(el.dataset.t);
  for (const el of document.querySelectorAll("[data-t-label]")) el.setAttribute("aria-label", T(el.dataset.tLabel));
}
// what the page overlay says, in the same language
const pageStrings = () => ({ reading: T("page_reading"), new: T("page_new"), one: T("page_summary_one"), many: T("page_summary_many") });

// errors from the helper carry a code; each code has words for people (the raw message goes to the console)
function words(e) {
  console.warn("sahl:", e.message);
  return { closed: T("err_closed"), tab: T("err_tab"), empty: T("err_empty") }[e.code] || T("err_generic");
}
const docName = (d) => T(`doc_${d}`);

function show(which) {
  for (const id of ["pair", "work", "none"]) $(id).hidden = id !== which;
  $("dock").hidden = which !== "work";
}

// how many boxes the fill button will fill
function count() {
  const n = document.querySelectorAll("#fields input[type=checkbox]:checked").length;
  $("count").textContent = n ? String(n) : "";
}

function setReading(on) {
  document.body.classList.toggle("reading", on);
}

function node(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
// text from the page or a guide, in whatever script: isolated, so it sits at the popup's start and keeps its own punctuation
function iso(tag, cls, text) {
  const n = node(tag, cls);
  n.append(node("bdi", "", text));
  return n;
}

function send(type, extra = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type, ...extra }, (r) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      if (!r) return reject(new Error("no answer from the helper"));
      if (!r.ok) return reject(Object.assign(new Error(r.error || "failed"), { code: r.code }));
      resolve(r);
    });
  });
}

async function currentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw Object.assign(new Error("no tab"), { code: "tab" });
  tabId = tab.id;
}

function choosePerson(people) {
  const select = $("person");
  select.replaceChildren(...people.map((p) => new Option(p.name, p.id)));
  const chosen = plan?.person && people.some((p) => p.id === plan.person) ? plan.person : people[0]?.id || "";
  select.value = chosen;
  $("person-row").hidden = people.length < 2;
  return chosen;
}

const asking = (f) => f.unknown && !f.told;
const fillable = () => (plan?.fields || []).some((f) => !asking(f));

// "No, it's different" is remembered, so the same guess isn't offered every time the popup opens
let declined = new Set();
const declineKey = (f) => `${f.label}\u0000${f.suggest}`;
async function loadDeclined() {
  try {
    declined = new Set((await chrome.storage.local.get("declined")).declined || []);
  } catch {}
}
function decline(f) {
  declined.add(declineKey(f));
  void chrome.storage.local.set({ declined: [...declined].slice(-200) }).catch(() => {});
}

// a box no guide knows: offer the told detail the local model thinks it is, or ask the person to type it once
function askBox(f) {
  const box = node("div", "teach");
  const remember = async (type, extra) => {
    if (busy) return;
    try {
      await send(type, { id: f.element_id, ...extra });
      await scanPage();
    } catch (e) {
      note(words(e));
    }
  };
  if (f.suggest && !declined.has(declineKey(f))) {
    box.append(node("p", "", T("same_q", { label: f.label, concept: f.suggest })));
    const row = node("div", "teach-row");
    const yes = node("button", "primary", T("same_yes"));
    const no = node("button", "ghost", T("same_no"));
    yes.type = no.type = "button";
    yes.addEventListener("click", () => void remember("same", { concept: f.suggest }));
    no.addEventListener("click", () => {
      decline(f);
      const next = askBox(f);
      next.id = box.id;
      next.hidden = box.hidden;
      box.replaceWith(next);
      next.querySelector("input")?.focus();
    });
    row.append(yes, no);
    box.append(row);
    return box;
  }
  const form = node("form", "teach-row");
  const input = document.createElement("input");
  input.autocomplete = "off";
  input.dir = "auto";
  input.placeholder = T("type_here");
  input.setAttribute("aria-label", T("what_goes", { label: f.label }));
  const save = node("button", "primary", T("remember"));
  save.type = "submit";
  form.append(input, save);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (input.value.trim()) void remember("tell", { value: input.value, person: $("person").value || null });
  });
  box.append(node("p", "", T("unknown", { label: f.label })), form);
  return box;
}

function listFields(fields) {
  const list = $("fields");
  list.replaceChildren();
  if (!fields.length) {
    list.append(node("li", "empty", T("no_fields")));
    count();
    return;
  }
  // two groups: what I can fill (the main action, first), then the boxes I need to be told about, numbered as on the page
  const ready = node("ol");
  const ask = node("ol");
  let askNo = 0;
  for (const f of fields) {
    const isAsk = asking(f);
    const li = node("li");
    const row = node(isAsk ? "div" : "label", isAsk ? "field ask" : "field");
    let mark;
    if (isAsk) {
      mark = node("span", "num", String(++askNo));
      mark.setAttribute("aria-hidden", "true");
    } else {
      mark = document.createElement("input");
      mark.type = "checkbox";
      mark.checked = true;
      mark.dataset.id = f.element_id;
      mark.setAttribute("aria-label", T("fill_box", { label: f.label }));
      mark.addEventListener("change", count);
    }
    const text = node("span");
    text.append(iso("b", "", f.label));
    const why = [];
    if (f.seen && f.seen !== f.label) why.push(f.seen);
    if (f.needs) why.push(T("needs", { doc: docName(f.needs) }));
    if (f.told) why.push(T("told"));
    if (why.length) text.append(node("small", "", why.join(", ")));
    if (isAsk && f.suggest) text.append(node("small", "ask-help", T("may_know")));
    if (isAsk) {
      const toggle = node("button", "toggle", T("tell"));
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", T("tell_about", { label: f.label }));
      const panel = askBox(f);
      const id = `teach-${askNo}`;
      panel.id = id;
      panel.hidden = true;
      toggle.setAttribute("aria-controls", id);
      toggle.addEventListener("click", () => {
        const current = document.getElementById(id);
        if (!current) return;
        const open = current.hidden;
        current.hidden = !open;
        toggle.setAttribute("aria-expanded", String(open));
        toggle.textContent = T(open ? "close" : "tell");
        toggle.setAttribute("aria-label", T(open ? "close_about" : "tell_about", { label: f.label }));
        if (open) current.querySelector("input, button")?.focus();
      });
      row.append(mark, text, toggle);
      li.append(row, panel);
      ask.append(li);
    } else {
      row.append(mark, text);
      li.append(row);
      ready.append(li);
    }
  }
  for (const [ol, key, cls] of [[ready, "ready", ""], [ask, "new_fields", "ask"]]) {
    if (!ol.children.length) continue;
    const group = node("li", "group");
    const head = node("div", `section ${cls}`.trim());
    head.append(node("span", "", T(key)), node("em", "", String(ol.children.length)));
    group.append(head, ol);
    list.append(group);
  }
  count();
}

// while reading for the first time: the list's shape, so the popup doesn't jump when it arrives
function skeleton() {
  if ($("fields").children.length) return;
  const box = node("li", "skeleton");
  box.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 4; i++) box.append(node("i"));
  $("fields").append(box);
}

function showPlan(out) {
  plan = out;
  const g = $("guide");
  g.replaceChildren();
  if (out.guide) {
    g.append(iso("strong", "", out.guide.name || out.guide.id));
    g.append(iso("span", "", out.guide.about || T("matched")));
  } else if (out.fields?.length) {
    g.append(node("strong", "", T("no_guide")));
    g.append(node("span", "", T("no_guide_sub")));
  } else {
    g.append(node("strong", "", T("no_match")));
    g.append(node("span", "", T("no_match_sub", { key: KEY })));
  }
  const person = choosePerson(out.people || []);
  const fields = out.fields || [];
  listFields(fields);
  $("fill").disabled = !fillable();
  const asked = fields.filter(asking).length;
  if (!out.people?.length && fields.some((f) => !f.unknown)) note(T("need_docs"));
  else if (!fields.length) note(out.guide ? T("scroll") : "");
  else if (out.guide && out.confidence < 55) note(T("uncertain"));
  else if (asked) note(asked === 1 ? T("asked_one") : T("asked_many", { n: asked }));
  else note("");
  return person;
}

async function scanPage() {
  if (busy) return;
  busy = true;
  setReading(true);
  $("rescan").disabled = $("fill").disabled = true;
  status(T("reading"));
  note("");
  try {
    await currentTab();
    if ($("work").hidden && !$("fields").children.length) {
      show("work");
      $("guide").replaceChildren();
      skeleton();
    }
    const out = await send("scan", { tabId, person: $("person").value || null, strings: pageStrings() });
    show("work");
    showPlan(out);
    status(T("ready_status"));
  } catch (e) {
    if (e.code === "pair") {
      show("pair");
      status(T("not_paired"));
    } else {
      show("none");
      $("none-text").textContent = words(e);
      status(T("cant_read"));
    }
  } finally {
    busy = false;
    setReading(false);
    $("rescan").disabled = false;
    $("fill").disabled = !fillable();
  }
}

const FAILS = {
  "field is no longer on the page": "fail_gone",
  "no matching option": "fail_option",
  "the page does not allow typing here": "fail_locked",
  "the page did not keep the value": "fail_kept",
};
const labelOf = (id) => plan?.fields?.find((f) => f.element_id === id)?.label;

async function fillChosen() {
  if (busy) return;
  const ids = [...document.querySelectorAll("#fields input[type=checkbox]:checked")].map((x) => x.dataset.id);
  if (!ids.length) return note(T("choose_one"));
  busy = true;
  $("fill").disabled = $("rescan").disabled = true;
  note(T("filling"));
  try {
    const out = await send("fill", { tabId, ids, person: $("person").value || null, replace: $("replace").checked });
    if (out.needs_person) {
      note(T("choose_person"));
      $("person-row").hidden = false;
      return;
    }
    const results = out.results || [];
    const filled = results.filter((r) => r.ok && !r.skipped);
    const skipped = results.filter((r) => r.skipped).length;
    const failed = results.filter((r) => !r.ok);
    const missing = out.missing || [];
    const bits = [];
    if (filled.length) {
      const names = [...new Set(filled.map((r) => labelOf(r.element_id)).filter(Boolean))].join(", ");
      bits.push(filled.length === 1 ? T("filled_one", { names }) : T("filled_many", { n: filled.length, names }));
    }
    if (skipped) bits.push(T("skipped", { n: skipped }));
    for (const r of failed) bits.push(T("failed", { label: labelOf(r.element_id) || "?", why: T(FAILS[r.reason] || "fail_other") }));
    if (missing.length) {
      const needs = [...new Set(missing.map((m) => m.needs).filter(Boolean))];
      bits.push(needs.length ? T("add_for", { docs: needs.map(docName).join(T("and")), n: missing.length }) : T("no_value", { n: missing.length }));
    }
    note(bits.join(" ") || T("nothing"));
    status(T("done"));
  } catch (e) {
    note(words(e));
    status(T("cant_fill"));
    if (e.code === "pair") show("pair");
  } finally {
    busy = false;
    $("rescan").disabled = false;
    $("fill").disabled = !fillable();
  }
}

async function boot() {
  await Promise.all([loadStrings(), loadDeclined()]);
  useLanguage(navigator.language.slice(0, 2)); // until Sahl says which
  show("none");
  $("none-text").textContent = T("checking");
  try {
    const h = await send("health");
    if (h.error) throw Object.assign(new Error(h.error), { code: h.code });
    if (h.app !== "Sahl") throw Object.assign(new Error("not Sahl"), { code: "closed" });
    useLanguage(h.lang || "en");
    const t = await send("token");
    if (!t.token || !h.verified) {  // never paired, or the Sahl answering isn't the one this browser was paired with
      show("pair");
      status(T("not_paired"));
      $("code").focus();
      return;
    }
    await scanPage();
  } catch (e) {
    if (e.code === "pair") {
      show("pair");
      status(T("not_paired"));
    } else {
      show("none");
      $("none-text").textContent = words(e);
      status(T("unreachable"));
    }
  }
}

$("pair-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const button = e.submitter;
  if (button) button.disabled = true;
  status(T("pairing"));
  try {
    await send("pair", { code: $("code").value });
    await scanPage();
  } catch (err) {
    console.warn("sahl:", err.message);
    status(err.code === "closed" ? T("err_closed") : T("pair_failed"));
  } finally {
    if (button) button.disabled = false;
  }
});
$("rescan").addEventListener("click", () => void scanPage());
$("retry").addEventListener("click", () => void boot());
$("fill").addEventListener("click", () => void fillChosen());
$("clear").addEventListener("click", async () => {
  await send("clear", { tabId }).catch(() => {});
  note(T("marks_hidden"));
});

void boot();
