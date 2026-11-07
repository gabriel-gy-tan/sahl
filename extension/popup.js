const $ = (id) => document.getElementById(id);
const status = (s) => ($("status").textContent = s);
const note = (s) => ($("note").textContent = s || "");
let tabId = null;
let plan = null;
let busy = false;

function show(which) {
  for (const id of ["pair", "work", "none"]) $(id).hidden = id !== which;
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

function send(type, extra = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ type, ...extra }, (r) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      if (!r) return reject(new Error("Sahl's browser helper did not answer."));
      if (!r.ok) return reject(Object.assign(new Error(r.error || "Sahl couldn't do that."), { code: r.code }));
      resolve(r);
    });
  });
}

async function currentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw Object.assign(new Error("Open a web page first."), { code: "tab" });
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
const declined = new Set();  // boxes whose "same as …?" the person said no to: ask for the value instead

// a box no guide knows: offer the told detail the local model thinks it is, or ask the person to type it once
function askBox(f) {
  const box = node("div", "teach");
  const remember = async (type, extra) => {
    if (busy) return;
    try {
      await send(type, { id: f.element_id, ...extra });
      await scanPage();
    } catch (e) {
      note(e.message);
    }
  };
  if (f.suggest && !declined.has(f.element_id)) {
    box.append(node("p", "", `Is “${f.label}” the same as “${f.suggest}”?`));
    const row = node("div", "teach-row");
    const yes = node("button", "primary", "Yes, use it");
    const no = node("button", "ghost", "No, it's different");
    yes.type = no.type = "button";
    yes.addEventListener("click", () => void remember("same", { concept: f.suggest }));
    no.addEventListener("click", () => {
      declined.add(f.element_id);
      box.replaceWith(askBox(f));
    });
    row.append(yes, no);
    box.append(row);
    return box;
  }
  const form = node("form", "teach-row");
  const input = document.createElement("input");
  input.autocomplete = "off";
  input.placeholder = "Type it here";
  input.setAttribute("aria-label", `What goes in ${f.label}`);
  const save = node("button", "primary", "Remember");
  save.type = "submit";
  form.append(input, save);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (input.value.trim()) void remember("tell", { value: input.value, person: $("person").value || null });
  });
  box.append(node("p", "", `Sahl doesn't know “${f.label}” yet. Tell it once and it will remember.`), form);
  return box;
}

function listFields(fields) {
  const list = $("fields");
  list.replaceChildren();
  if (!fields.length) {
    const li = node("li", "empty", "No fields on this page match this form's guide.");
    list.append(li);
    return;
  }
  for (const f of fields) {
    const li = node("li");
    const label = node("label", "field");
    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = !asking(f);
    check.disabled = asking(f);
    check.dataset.id = f.element_id;
    check.setAttribute("aria-label", `Fill ${f.label}`);
    const text = node("span");
    text.append(node("b", "", f.label));
    const why = [];
    if (f.seen && f.seen !== f.label) why.push(f.seen);
    if (f.needs) why.push(`needs ${f.needs}`);
    if (f.told) why.push("you told Sahl");
    if (f.confidence < 90) why.push(`${f.confidence}% match`);
    if (why.length) text.append(node("small", "", why.join(" · ")));
    const kind = node("em", "", f.kind === "date-parts" ? "date" : f.kind);
    label.append(check, text, kind);
    li.append(label);
    if (asking(f)) li.append(askBox(f));
    list.append(li);
  }
}

function showPlan(out) {
  plan = out;
  const g = $("guide");
  g.replaceChildren();
  if (out.guide) {
    g.append(node("strong", "", out.guide.name || out.guide.id));
    const sub = out.guide.about || "Matched from this page's fields.";
    g.append(node("span", "", sub));
  } else if (out.fields?.length) {
    g.append(node("strong", "", "No form guide for this page"));
    g.append(node("span", "", "Sahl fills what you told it before, and asks about the rest."));
  } else {
    g.append(node("strong", "", "No guide matched this page"));
    g.append(node("span", "", out.reason || "Try Sahl's screen reader instead."));
  }
  const person = choosePerson(out.people || []);
  const fields = out.fields || [];
  listFields(fields);
  $("fill").disabled = !fillable();
  const asked = fields.filter(asking).length;
  if (!out.people?.length && fields.some((f) => !f.unknown)) note("Add a passport or Emirates ID in Sahl to fill the document boxes.");
  else if (!fields.length) note(out.reason || "Scroll to the form and scan again.");
  else if (out.guide && out.confidence < 55) note("This match is uncertain. Check the highlighted boxes before filling.");
  else if (asked) note(`Sahl doesn't know ${asked} ${asked === 1 ? "box" : "boxes"} yet (dashed on the page). Tell it once below.`);
  else note("");
  return person;
}

async function scanPage() {
  if (busy) return;
  busy = true;
  setReading(true);
  $("rescan").disabled = $("fill").disabled = true;
  status("Reading the page…");
  note("");
  try {
    await currentTab();
    const out = await send("scan", { tabId, person: $("person").value || null });
    show("work");
    showPlan(out);
    status("Ready. Check the marks on the page.");
  } catch (e) {
    if (e.code === "pair") {
      show("pair");
      status("Pair with Sahl first.");
    } else {
      show("none");
      $("none-text").textContent = e.message;
      status("Couldn't read this page.");
    }
  } finally {
    busy = false;
    setReading(false);
    $("rescan").disabled = false;
    $("fill").disabled = !fillable();
  }
}

async function fillChosen() {
  if (busy) return;
  const ids = [...document.querySelectorAll("#fields input[type=checkbox]:checked")].map((x) => x.dataset.id);
  if (!ids.length) return note("Choose at least one box to fill.");
  busy = true;
  $("fill").disabled = $("rescan").disabled = true;
  note("Filling the boxes you chose…");
  try {
    const out = await send("fill", { tabId, ids, person: $("person").value || null, replace: $("replace").checked });
    if (out.needs_person) {
      note("Choose whose documents this form is for, then fill again.");
      $("person-row").hidden = false;
      return;
    }
    const filled = (out.results || []).filter((r) => r.ok && !r.skipped);
    const done = filled.length;
    const skipped = (out.results || []).filter((r) => r.skipped).length;
    const failed = (out.results || []).filter((r) => !r.ok);
    const missing = out.missing || [];
    const bits = [];
    if (done) {
      const names = [...new Set(filled.map((r) => plan?.fields?.find((f) => f.element_id === r.element_id)?.label).filter(Boolean))];
      bits.push(`Filled ${done} ${done === 1 ? "box" : "boxes"}${names.length ? `: ${names.join(", ")}` : ""}.`);
    }
    if (skipped) bits.push(`${skipped} already had a value, so Sahl left ${skipped === 1 ? "it" : "them"} alone. Tick "Replace values already in the boxes" to overwrite.`);
    if (failed.length) bits.push(failed.map((r) => `${plan?.fields?.find((f) => f.element_id === r.element_id)?.label || "A box"}: ${r.reason || "the page did not accept the value"}.`).join(" "));
    if (missing.length) {
      const needs = [...new Set(missing.map((m) => m.needs).filter(Boolean))];
      bits.push(needs.length ? `Add ${needs.join(" and ")} for ${missing.length} more.` : `${missing.length} ${missing.length === 1 ? "box has" : "boxes have"} no verified value yet.`);
    }
    note(bits.join(" ") || "Nothing was filled.");
    status("Done. Check the page, then submit it yourself.");
  } catch (e) {
    note(e.message);
    status("Couldn't fill.");
    if (e.code === "pair") show("pair");
  } finally {
    busy = false;
    $("rescan").disabled = false;
    $("fill").disabled = !fillable();
  }
}

async function boot() {
  show("none");
  $("none-text").textContent = "Looking for Sahl on this computer…";
  status("Looking for Sahl…");
  try {
    const h = await send("health");
    if (h.error) throw Object.assign(new Error(h.error), { code: h.code });
    if (h.app !== "Sahl") throw new Error("Sahl's browser bridge is not ready.");
    const t = await send("token");
    if (!t.token) {
      show("pair");
      status("Not paired yet.");
      $("code").focus();
      return;
    }
    await scanPage();
  } catch (e) {
    if (e.code === "pair") {
      show("pair");
      status("Pair with Sahl first.");
    } else {
      show("none");
      $("none-text").textContent = e.message;
      status("Sahl isn't reachable.");
    }
  }
}

$("pair-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const button = e.submitter;
  if (button) button.disabled = true;
  status("Pairing…");
  try {
    await send("pair", { code: $("code").value });
    status("Paired.");
    await scanPage();
  } catch (err) {
    status(err.message);
  } finally {
    if (button) button.disabled = false;
  }
});
$("rescan").addEventListener("click", () => void scanPage());
$("retry").addEventListener("click", () => void scanPage());
$("fill").addEventListener("click", () => void fillChosen());
$("clear").addEventListener("click", async () => {
  await send("clear", { tabId }).catch(() => {});
  note("Marks cleared.");
});

void boot();
