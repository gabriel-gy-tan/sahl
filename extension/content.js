(() => {
  const version = "6";
  if (window.__sahlVersion === version) return;
  window.__sahlVersion = version;
  window.__sahlLoaded = true;
  document.querySelectorAll("[data-sahl-overlay]").forEach((node) => node.remove());

  const targets = new Map();
  const keys = new WeakMap();
  // never read or filled: passwords, PINs, one-time codes, a card's security code (the same rule as the sidecar's taught.NEVER)
  const never = /pass(?:word|code|phrase)|passwd|(?<![a-z])pwd(?![a-z])|(?<![a-z])[mt]?pin(?:code)?(?![a-z])|(?<![a-z])t?otp(?:code)?(?![a-z])|(?<![a-z])(?:cv[cv]\d?|csc)(?![a-z])|one.time|card\s*verification|security\s*code|verification\s*(?:code|number|value)|(?:sms|auth(?:entication)?|access|\d+.?digit)\s*code|كلمة\s*(?:ال)?(?:مرور|سر)|(?:ال)?(?:رقم|رمز)\s*(?:ال)?(?:سري|تحقق|تأكيد|مرور)|لمرة\s*واحدة/i;
  const skipTypes = new Set(["hidden", "password", "file", "submit", "button", "reset", "image", "range", "color", "time"]);
  let seq = 0;

  const text = (el) => (typeof el === "string" ? el : String(el?.innerText ?? el?.textContent ?? ""))
    .replace(/\s+/g, " ").trim().slice(0, 300);
  const norm = (s) => String(s ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const key = (el) => {
    let id = keys.get(el);
    if (!id) keys.set(el, (id = `e${++seq}`));
    return id;
  };
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
  };
  const shown = (el) => {
    if (!el || !el.isConnected || el.disabled || el.readOnly) return false;
    if (typeof el.checkVisibility === "function" && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1;
  };
  const labelled = (el) => {
    const out = [];
    const add = (v) => {
      const s = text(v);
      if (s && !out.includes(s)) out.push(s);
    };
    if (el.getAttribute("aria-labelledby")) {
      for (const id of el.getAttribute("aria-labelledby").split(/\s+/)) add(document.getElementById(id));
    }
    add(el.getAttribute("aria-label"));
    if (el.labels) for (const l of el.labels) add(l);
    add(el.closest("label"));
    const cell = el.closest("td, th");
    if (cell) {
      const row = cell.closest("tr");
      if (row) {
        const cells = [...row.children].filter((x) => /^(TD|TH)$/.test(x.tagName));
        for (let i = cells.indexOf(cell) - 1; i >= 0; i--) {
          if (cells[i].querySelector("input, select, textarea, button")) continue;
          const s = text(cells[i]);
          if (s) { add(s); break; }
        }
      }
      if (!cell.querySelector("input, select, textarea, button")) add(cell);
    }
    for (let pn = el.previousSibling; pn; pn = pn.previousSibling) {
      if (text(pn)) {
        if (pn.nodeType === 3) add(pn.textContent);
        break;
      }
    }
    // labels are often a sibling of the input's wrapper, not the input (<div>First Name</div><div><input></div>)
    let box = el;
    outer: for (let depth = 0; box && depth < 4; depth++, box = box.parentElement) {
      let prev = box.previousElementSibling;
      for (let i = 0; prev && i < 3; i++, prev = prev.previousElementSibling) {
        if (prev.matches?.("input, select, textarea, button") || prev.querySelector?.("input, select, textarea, button")) break;
        const s = text(prev);
        if (s) { add(s); break outer; }
      }
    }
    const group = el.closest("fieldset");
    if (group) add(group.querySelector("legend"));
    return out;
  };
  const secret = (el, labels) => {
    const type = String(el.getAttribute("type") || "").toLowerCase();
    if (skipTypes.has(type) || el.tagName === "BUTTON" || el.readOnly || el.disabled) return true;
    if (el.tagName === "SELECT" && el.multiple) return true;
    const bit = [el.getAttribute("autocomplete"), el.getAttribute("name"), el.id, el.getAttribute("placeholder"), ...(labels || [])].join(" ");
    return never.test(bit);
  };
  const labelOf = (labels) => labels.find((x) => !/^(day|month|year|dd|mm|yy|yyyy)$/i.test(x)) || labels[0] || "";
  const partOf = (el, labels) => {
    const raw = [el.getAttribute("name"), el.id, el.getAttribute("placeholder")].filter(Boolean).join(" ")
      .replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_\-\[\].]+/g, " ")
      .replace(/\b(dob|dateofbirth|birth(?!day)|exp(?:iry)?|issue|start|end)(month|day|year|mm|dd|yy|yyyy)\b/gi, "$1 $2");
    const bit = [raw, el.options?.[0]?.text, ...labels].filter(Boolean).join(" ");
    if (/(^|[^a-z])(day|dd)([^a-z]|$)/i.test(bit) && !/(^|[^a-z])(month|mm|year|yy|yyyy)([^a-z]|$)/i.test(bit)) return "d";
    if (/(^|[^a-z])(month|mm)([^a-z]|$)/i.test(bit) && !/(^|[^a-z])(day|dd|year|yy|yyyy)([^a-z]|$)/i.test(bit)) return "m";
    if (/(^|[^a-z])(year|yy|yyyy)([^a-z]|$)/i.test(bit) && !/(^|[^a-z])(day|dd|month|mm)([^a-z]|$)/i.test(bit)) return "y";
    return "";
  };
  const optionText = (el) => text(el) || String(el.getAttribute("aria-label") || "").trim();
  const plain = (el, labels) => ({
    element_id: key(el), label: labelOf(labels), labels: labels.slice(0, 8),
    placeholder: String(el.getAttribute("placeholder") || "").slice(0, 200),
    name: String(el.getAttribute("name") || "").slice(0, 200),
    tag: el.tagName.toLowerCase(), type: String(el.getAttribute("type") || "").toLowerCase(),
    autocomplete: String(el.getAttribute("autocomplete") || "").slice(0, 100), rect: rect(el),
  });

  const scan = () => {
    const radios = new Map();
    const normal = [];
    const dates = [];
    const elements = [...document.querySelectorAll("input, select, textarea")];
    for (const el of elements) {
      if (!shown(el)) continue;
      const labels = labelled(el);
      if (secret(el, labels)) continue;
      if (el.tagName === "INPUT" && el.type === "radio") {
        const group = `${el.form ? key(el.form) : "page"}|${el.name || key(el)}`;
        if (!radios.has(group)) radios.set(group, []);
        radios.get(group).push({ el, labels });
        continue;
      }
      const base = plain(el, labels);
      const part = partOf(el, labels);
      if (part && (el.tagName === "SELECT" || (el.tagName === "INPUT" && !["date", "month", "week", "datetime-local"].includes(el.type)))) {
        const fs = el.closest("fieldset");
        const stem = String(el.getAttribute("name") || el.id || "")
          .replace(/(?:day|dd|month|mm|year|yy|yyyy)$/i, "").replace(/\d+/g, "#").replace(/[^a-z#]/gi, "");
        const group = `${el.form ? key(el.form) : "page"}|${fs ? key(fs) : ""}|${stem || (el.parentElement ? key(el.parentElement) : "date")}`;
        dates.push({ el, labels, part, group, base });
        continue;
      }
      if (el.tagName === "SELECT") {
        base.options = [...el.options].filter((o) => !o.disabled).map((o) => ({ text: optionText(o), value: o.value, selected: o.selected }));
      }
      normal.push(base);
      targets.set(base.element_id, { kind: base.tag === "select" ? "select" : "text", el, options: base.options || [] });
    }

    for (const [group, list] of radios) {
      if (!list.length) continue;
      const options = list.map(({ el }) => {
        const labels = labelled(el);
        return { element_id: key(el), text: labelOf(labels) || optionText(el) || String(el.getAttribute("value") || ""), value: el.value, el };
      });
      const first = list[0].el;
      const legend = text(first.closest("fieldset")?.querySelector("legend"));
      const groupLabel = legend || first.closest("[role=radiogroup]")?.getAttribute("aria-label") || labelOf(list[0].labels);
      const id = key(first);
      normal.push({
        element_id: id, label: groupLabel || "Choice", labels: [groupLabel, ...list.flatMap((x) => x.labels)].filter(Boolean).slice(0, 8),
        placeholder: "", name: first.name || "", tag: "radio", type: "radio", autocomplete: "", rect: rect(first),
        options: options.map(({ element_id, text, selected }) => ({ element_id, text, selected })),
      });
      targets.set(id, { kind: "radio", options });
    }

    const chunks = new Map();
    for (const d of dates) {
      if (!chunks.has(d.group)) chunks.set(d.group, []);
      chunks.get(d.group).push(d);
    }
    const loose = [];  // a month and a year with no day (a card's expiry): each is its own box
    for (const list of chunks.values()) {
      for (let i = 0; i < list.length; i += 3) {
        const three = list.slice(i, i + 3);
        const found = new Map(three.map((x) => [x.part, x]));
        if (found.size !== 3) {
          loose.push(...three);
          continue;
        }
        const parts = ["d", "m", "y"].map((p) => found.get(p));
        const first = parts[0].base;
        const box = parts[0].el.closest("fieldset");
        const legend = text(box?.querySelector("legend"));
        const label = legend || labelOf(parts.flatMap((p) => p.labels)) || "Date";
        const id = first.element_id;
        normal.push({
          element_id: id, label, labels: [label, ...parts.flatMap((p) => p.labels)].slice(0, 8),
          placeholder: "", name: parts[0].base.name, tag: "date-parts", type: "date",
          autocomplete: "", rect: rect(parts[0].el), parts: parts.map((p) => ({ element_id: p.base.element_id, part: p.part })),
        });
        targets.set(id, { kind: "date-parts", parts: parts.map((p) => ({ part: p.part, el: p.el })) });
      }
    }
    for (const { el, labels, part, base } of loose) {
      const word = { d: "day", m: "month", y: "year" }[part];
      const main = labels.find((x) => !/^(day|month|year|dd|mm|yy|yyyy)$/i.test(x));
      base.label = main ? `${main} (${word})` : base.label || word;  // two boxes under one label are two details
      if (el.tagName === "SELECT") {
        base.options = [...el.options].filter((o) => !o.disabled).map((o) => ({ text: optionText(o), value: o.value, selected: o.selected }));
      }
      normal.push(base);
      targets.set(base.element_id, { kind: base.tag === "select" ? "select" : "text", el, options: base.options || [] });
    }

    return {
      url: location.href, title: document.title,
      headings: [...document.querySelectorAll("h1, h2, h3")].map(text).filter(Boolean).slice(0, 10).join(" | "),
      fields: normal,
    };
  };

  let host = null;
  let shadow = null;
  let root = null;
  let rings = [];
  let frame = 0;
  let reading = false;
  let timer = 0;
  const clear = () => {
    reading = false;
    if (timer) clearTimeout(timer);
    timer = 0;
    rings = [];
    if (root) root.replaceChildren();
    if (host) host.remove();
    host = shadow = root = null;
  };
  const showReading = () => {
    clear();
    reading = true;
    host = document.createElement("div");
    host.setAttribute("data-sahl-overlay", "1");
    host.style.cssText = "position:fixed;inset:0;z-index:2147483647;pointer-events:none;";
    shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `.pill{position:fixed;top:18px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:9px;padding:9px 13px;border-radius:999px;background:#0d2b17;color:#d8ffe2;font:600 12px/1.2 system-ui,sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.35),0 0 0 1px rgba(61,220,115,.35)}.dot{width:13px;height:13px;border-radius:50%;border:2px solid rgba(61,220,115,.25);border-top-color:#3ddc73;animation:sahl-spin .7s linear infinite}@keyframes sahl-spin{to{transform:rotate(360deg)}}`;
    root = document.createElement("div");
    const pill = document.createElement("div");
    pill.className = "pill";
    const dot = document.createElement("span");
    dot.className = "dot";
    pill.append(dot, "Sahl is reading this page…");
    root.append(pill);
    shadow.append(style, root);
    document.documentElement.append(host);
    timer = setTimeout(() => { if (reading) clear(); }, 12000);
  };
  const place = () => {
    frame = 0;
    if (!root) return;
    for (const { el, node } of rings) {
      const r = el.isConnected ? el.getBoundingClientRect() : null;
      const on = r && r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
      node.style.display = on ? "block" : "none";
      if (!on) continue;
      node.style.left = `${Math.round(r.left - 3)}px`;
      node.style.top = `${Math.round(r.top - 3)}px`;
      node.style.width = `${Math.round(r.width + 6)}px`;
      node.style.height = `${Math.round(r.height + 6)}px`;
    }
  };
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(place);
  };
  const render = (fields) => {
    clear();
    if (!fields.length) return;
    host = document.createElement("div");
    host.setAttribute("data-sahl-overlay", "1");
    host.style.cssText = "position:fixed;inset:0;z-index:2147483647;pointer-events:none;";
    shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `.ring{position:absolute;box-sizing:border-box;border:2px solid #34c759;border-radius:8px;background:rgba(52,199,89,.08);box-shadow:0 0 0 2px rgba(52,199,89,.18);}.tag{position:absolute;left:0;bottom:100%;margin-bottom:5px;max-width:260px;padding:4px 7px;border-radius:6px;background:#10351d;color:#d8ffe2;font:600 11px/1.2 system-ui,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-shadow:0 2px 8px rgba(0,0,0,.25);}.ask{border-style:dashed;border-color:#e0a800;background:rgba(242,193,78,.07);box-shadow:none;}.ask .tag{background:#3a2c05;color:#ffe9a8;}`;
    root = document.createElement("div");
    shadow.append(style, root);
    for (const f of fields) {
      const target = targets.get(f.element_id);
      if (!target) continue;
      const els = target.kind === "date-parts" ? target.parts.map((p) => p.el)
        : target.kind === "radio" ? target.options.map((o) => o.el) : [target.el];
      const live = els.filter((e) => e?.isConnected);
      if (!live.length) continue;
      for (const el of live) {
        const node = document.createElement("div");
        const ask = f.unknown && !f.told;  // a box Sahl doesn't know yet: dashed amber, until the person tells it
        node.className = ask ? "ring ask" : "ring";
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = ask ? `Tell Sahl: ${f.label}` : f.label;
        node.append(tag);
        root.append(node);
        rings.push({ el, node });
      }
    }
    if (!rings.length) return clear();
    document.documentElement.append(host);
    place();
    return { ok: true };
  };

  const set = (el, value) => {
    const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype
      : el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(el, value); else el.value = value;
    const input = typeof InputEvent === "function"
      ? new InputEvent("input", { bubbles: true, composed: true, data: String(value), inputType: "insertText" })
      : new Event("input", { bubbles: true, composed: true });
    el.dispatchEvent(input);
    el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
  };
  const typeText = (el, value) => {
    const want = String(value ?? "");
    el.focus();
    try { el.select(); } catch {}
    try { document.execCommand("insertText", false, want); } catch {}
    if (String(el.value ?? "") !== want) set(el, want);
  };
  const empty = (el) => {
    if (el instanceof HTMLSelectElement) {
      const o = el.options[el.selectedIndex];
      const label = text(o);
      // a menu with no "Select…" entry shows its first option until someone picks: that is not a value yet
      const untouched = el.selectedIndex === 0 && ![...el.options].some((x) => x.defaultSelected);
      return !el.value || !o || untouched
        || /^(?:select|choose|please select|--|none|m|d|y|mm|dd|yy|yyyy|month|day|year|select (?:month|day|year))$/i.test(label);
    }
    const value = String(el.value || "").trim();
    const placeholder = String(el.getAttribute("placeholder") || "").trim();
    return !value || Boolean(placeholder && value.toLowerCase() === placeholder.toLowerCase());
  };
  const matchOption = (options, want) => {
    const wants = (Array.isArray(want) ? want : [want]).map(norm).filter(Boolean).sort((a, b) => b.length - a.length);
    if (!wants.length) return undefined;
    for (const w of wants) {
      const exact = options.find((o) => norm(o.text) === w);
      if (exact) return exact;
    }
    return options.find((o) => {
      const n = norm(o.text);
      return n && wants.some((w) => n.includes(w) || w.includes(n));
    });
  };
  const fillOne = (v, replace) => {
    const t = targets.get(v.element_id);
    if (!t) return { element_id: v.element_id, ok: false, reason: "field is no longer on the page" };
    if (t.kind === "date-parts") {
      if (!replace && t.parts.some((p) => !empty(p.el))) return { element_id: v.element_id, ok: true, skipped: "already has a value" };
      let ok = true;
      for (const part of v.parts || []) {
        const target = t.parts.find((p) => p.part === part.part);
        if (!target) { ok = false; continue; }
        if (target.el instanceof HTMLSelectElement) {
          const choice = matchOption([...target.el.options].map((o) => ({ text: optionText(o), el: o })),
            part.texts?.length ? part.texts : part.value);
          if (!choice) { ok = false; continue; }
          const at = [...target.el.options].indexOf(choice.el);
          target.el.selectedIndex = at;
          set(target.el, choice.el.value);
          ok = ok && target.el.selectedIndex === at;
        } else {
          set(target.el, part.value);
          ok = ok && !empty(target.el);
        }
      }
      return { element_id: v.element_id, ok };
    }
    if (t.kind === "radio") {
      if (!replace && t.options.some((o) => o.el.checked)) return { element_id: v.element_id, ok: true, skipped: "already chosen" };
      const choice = matchOption(t.options.map((o) => ({ ...o, text: o.text })), v.option);
      if (!choice) return { element_id: v.element_id, ok: false, reason: "no matching option" };
      choice.el.click();
      return { element_id: v.element_id, ok: Boolean(choice.el.checked) };
    }
    if (t.kind === "select") {
      if (!replace && !empty(t.el)) return { element_id: v.element_id, ok: true, skipped: "already has a value" };
      const choice = matchOption(t.options, v.option);
      if (!choice) return { element_id: v.element_id, ok: false, reason: "no matching option" };
      const at = [...t.el.options].findIndex((o) => norm(optionText(o)) === norm(choice.text));
      if (at < 0) return { element_id: v.element_id, ok: false, reason: "no matching option" };
      t.el.selectedIndex = at;
      set(t.el, t.el.options[at].value);
      return { element_id: v.element_id, ok: t.el.selectedIndex === at };
    }
    if (!replace && !empty(t.el)) return { element_id: v.element_id, ok: true, skipped: "already has a value" };
    if (t.el.readOnly || t.el.disabled) return { element_id: v.element_id, ok: false, reason: "the page does not allow typing here" };
    typeText(t.el, v.value);
    return { element_id: v.element_id, ok: String(t.el.value ?? "") === String(v.value ?? "") };
  };
  const fill = async (values, replace) => {
    const results = values.map((v) => fillOne(v, replace));
    await new Promise((done) => setTimeout(done, 60));
    for (let i = 0; i < results.length; i++) {
      const result = results[i];
      const value = values[i];
      if (!result.ok || result.skipped) continue;
      const target = targets.get(value.element_id);
      if (!target || target.kind !== "text") continue;
      const want = String(value.value ?? "");
      if (String(target.el.value ?? "") === want) continue;
      typeText(target.el, want);
      await new Promise((done) => setTimeout(done, 30));
      if (String(target.el.value ?? "") !== want) {
        result.ok = false;
        result.reason = "the page did not keep the value";
      }
    }
    return results;
  };

  addEventListener("scroll", schedule, { capture: true, passive: true });
  addEventListener("resize", schedule, { passive: true });
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    const type = String(msg?.type || "");
    const mine = (name) => type === `sahl:v${version}:${name}`;
    if (mine("scan")) { showReading(); reply(scan()); return true; }
    if (mine("read-end")) { if (reading) clear(); reply({ ok: true }); return true; }
    if (mine("render")) { reply(render(msg.fields || [])); return true; }
    if (mine("fill")) {
      fill(msg.values || [], Boolean(msg.replace)).then(reply, () => reply([]));
      return true;
    }
    if (mine("clear")) { clear(); reply({ ok: true }); return true; }
    return false;
  });
  addEventListener("pagehide", clear, { once: true });
})();
