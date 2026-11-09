(() => {
  const version = "8";
  if (window.__sahlVersion === version) return;
  window.__sahlVersion = version;
  window.__sahlLoaded = true;
  document.querySelectorAll("[data-sahl-overlay]").forEach((node) => node.remove());

  const targets = new Map();
  const keys = new WeakMap();
  let byEl = new WeakMap();
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
  // what the person sees for a box: a menu that a widget (Select2, Chosen…) hid at 1px is seen as the widget beside it
  const face = (el) => {
    const r = el.getBoundingClientRect();
    if (el.tagName !== "SELECT" || (r.width > 4 && r.height > 4)) return el;
    for (let x = el.nextElementSibling; x; x = x.nextElementSibling) {
      const b = x.getBoundingClientRect();
      if (b.width > 10 && b.height > 10) return x;
    }
    return el;
  };
  const rect = (el) => {
    const r = face(el).getBoundingClientRect();
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
  // what a menu says when it has no real name ("Select box", "Please select"): the label beside it is the better name
  const generic = /^(?:please\s+)?(?:select|choose)(?:\s+(?:box|one|an? option|option))?\.{0,3}$|^(?:select|dropdown|combobox|search|--.*--)$/i;
  const labelOf = (labels) => labels.find((x) => !/^(day|month|year|dd|mm|yy|yyyy)$/i.test(x) && !generic.test(x)) || labels.find((x) => !generic.test(x)) || labels[0] || "";
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
      targets.set(id, { kind: "radio", options, box: first.closest("fieldset") || first.closest("[role=radiogroup]") || first.parentElement });
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
      url: location.origin + location.pathname, title: document.title,
      headings: [...document.querySelectorAll("h1, h2, h3")].map(text).filter(Boolean).slice(0, 10).join(" | "),
      fields: normal,
    };
  };

  let host = null;
  let shadow = null;
  let root = null;
  let rings = [];
  let active = null;
  let frame = 0;
  let reading = false;
  let timer = 0;
  const clear = () => {
    reading = false;
    if (timer) clearTimeout(timer);
    timer = 0;
    rings = [];
    active = null;
    byEl = new WeakMap();
    if (root) root.replaceChildren();
    if (host) host.remove();
    host = shadow = root = null;
  };
  let words = {}; // from the popup, in Sahl's language
  const say = (k, fallback, n) => (words[k] || fallback).replaceAll("{n}", String(n ?? ""));
  const showReading = () => {
    clear();
    if (window !== window.top) return; // one pill per tab
    reading = true;
    host = document.createElement("div");
    host.setAttribute("data-sahl-overlay", "1");
    host.style.cssText = "position:fixed;inset:0;z-index:2147483647;pointer-events:none;";
    shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `*{pointer-events:none}.pill{position:fixed;top:16px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:8px;padding:8px 14px 8px 10px;border-radius:999px;background:rgba(10,10,11,.92);color:#ededef;font:500 12px/1.2 system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:-.005em;box-shadow:0 0 0 1px rgba(255,255,255,.08),0 10px 30px rgba(0,0,0,.35);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);animation:sahl-in .2s cubic-bezier(.2,.8,.2,1)}.dot{width:12px;height:12px;border-radius:50%;border:1.5px solid rgba(43,184,163,.22);border-top-color:#2bb8a3;animation:sahl-spin .8s linear infinite}@keyframes sahl-spin{to{transform:rotate(360deg)}}@keyframes sahl-in{from{opacity:0;transform:translate(-50%,-4px)}}@media (prefers-reduced-motion: reduce){.pill,.dot{animation:none}}`;
    root = document.createElement("div");
    const pill = document.createElement("div");
    pill.className = "pill";
    const dot = document.createElement("span");
    dot.className = "dot";
    pill.append(dot, say("reading", "Reading this page…"));
    root.append(pill);
    shadow.append(style, root);
    document.documentElement.append(host);
    timer = setTimeout(() => { if (reading) clear(); }, 12000);
  };
  const bounds = (els) => {
    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const el of els) {
      if (!el?.isConnected) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      left = Math.min(left, r.left);
      top = Math.min(top, r.top);
      right = Math.max(right, r.right);
      bottom = Math.max(bottom, r.bottom);
    }
    return left === Infinity ? null : { left, top, right, bottom, width: right - left, height: bottom - top };
  };
  const place = () => {
    frame = 0;
    if (!root) return;
    let tipRing = null;
    for (const ring of rings) {
      const r = bounds(ring.els);
      const on = r && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
      ring.node.style.display = on ? "block" : "none";
      if (!on) continue;
      ring.node.style.left = `${Math.round(r.left - 3)}px`;
      ring.node.style.top = `${Math.round(r.top - 3)}px`;
      ring.node.style.width = `${Math.round(r.width + 6)}px`;
      ring.node.style.height = `${Math.round(r.height + 6)}px`;
      ring.node.classList.toggle("active", ring === active);
      if (ring === active) tipRing = { ring, r };
    }
    const tip = root.querySelector(".tip");
    if (!tip) return;
    if (!tipRing) { tip.style.display = "none"; return; }
    tip.className = tipRing.ring.ask ? "tip ask" : "tip";
    tip.replaceChildren();
    tip.append(document.createElement("b"));
    tip.firstChild.textContent = tipRing.ring.label;
    if (tipRing.ring.ask) {
      const extra = document.createElement("span");
      extra.textContent = ` · ${say("new", "new box {n}", tipRing.ring.n)}`;
      tip.append(extra);
    }
    tip.style.display = "block";
    const w = tip.offsetWidth, h = tip.offsetHeight;
    const left = Math.min(Math.max(8, tipRing.r.left), innerWidth - w - 8);
    let top = tipRing.r.top - h - 7;
    if (top < 8) top = Math.min(innerHeight - h - 8, tipRing.r.bottom + 7);
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(top)}px`;
  };
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(place);
  };
  const render = (fields, total, first = 0) => {
    clear();
    if (!fields.length) return;
    host = document.createElement("div");
    host.setAttribute("data-sahl-overlay", "1");
    host.style.cssText = "position:fixed;inset:0;z-index:2147483647;pointer-events:none;";
    shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    // quiet until the pointer or focus reaches a box; never takes a click (the host and everything in it ignore the pointer)
    // the filled tick is Phosphor's "check" icon (bold weight, MIT licence)
    style.textContent = `
      *{pointer-events:none}
      .ring{position:absolute;box-sizing:border-box;border:1px solid transparent;border-radius:8px;transition:border-color .18s ease,box-shadow .18s ease}
      .ring.ask{border:1px dashed rgba(240,166,64,.55)}
      .ring.active{border-color:rgba(43,184,163,.8);box-shadow:0 0 0 3px rgba(43,184,163,.14)}
      .ring.ask.active{border-style:solid;border-color:rgba(240,166,64,.85);box-shadow:0 0 0 3px rgba(240,166,64,.14)}
      .ring .dot{position:absolute;right:-3px;top:-3px;width:6px;height:6px;border-radius:50%;background:#2bb8a3;box-shadow:0 0 0 1.5px rgba(255,255,255,.9)}
      .ring .num{position:absolute;right:-8px;top:-8px;min-width:16px;height:16px;padding:0 4px;box-sizing:border-box;border-radius:999px;display:grid;place-items:center;background:#f0a640;color:#241402;font:650 10px/1 system-ui,-apple-system,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums;box-shadow:0 0 0 1.5px rgba(255,255,255,.9),0 1px 4px rgba(0,0,0,.25)}
      .tip{position:absolute;z-index:2;max-width:260px;padding:6px 10px;border-radius:8px;background:rgba(10,10,11,.94);color:#ededef;font:500 11.5px/1.3 system-ui,-apple-system,"Segoe UI",sans-serif;box-shadow:0 0 0 1px rgba(255,255,255,.08),0 8px 24px rgba(0,0,0,.3);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .tip b{font-weight:600}
      .tip span{color:#f0a640}
      .summary{position:fixed;z-index:1;top:16px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:8px;padding:8px 14px 8px 12px;border-radius:999px;background:rgba(10,10,11,.92);color:#ededef;font:500 12px/1.2 system-ui,-apple-system,"Segoe UI",sans-serif;box-shadow:0 0 0 1px rgba(255,255,255,.08),0 10px 30px rgba(0,0,0,.35);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);white-space:nowrap}
      .summary i{width:6px;height:6px;border-radius:50%;background:#f0a640;box-shadow:0 0 0 3px rgba(240,166,64,.18)}
      .ring.done{border:1px solid rgba(43,184,163,.75);box-shadow:none}
      .ring.done .dot{right:-7px;top:-7px;width:14px;height:14px;background:#2bb8a3 url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 256 256' fill='%2303120f'%3E%3Cpath d='M232.49,80.49l-128,128a12,12,0,0,1-17,0l-56-56a12,12,0,1,1,17-17L96,183,215.51,63.51a12,12,0,0,1,17,17Z'/%3E%3C/svg%3E") center/9px no-repeat;box-shadow:0 0 0 1.5px rgba(255,255,255,.9),0 1px 4px rgba(0,0,0,.25);animation:sahl-pop .3s cubic-bezier(.3,1.4,.5,1)}
      @keyframes sahl-pop{from{transform:scale(.4);opacity:0}}
      @media (prefers-reduced-motion: reduce){.ring,.ring .dot{transition:none;animation:none}}
    `;
    root = document.createElement("div");
    shadow.append(style, root);
    // one summary for the tab, on the page itself, counting the boxes in its frames too
    const asked = typeof total === "number" ? total : fields.filter((f) => f.unknown && !f.told).length;
    if (asked && window === window.top) {
      const summary = document.createElement("div");
      summary.className = "summary";
      summary.append(document.createElement("i"), asked === 1 ? say("one", "1 new box · open Sahl") : say("many", "{n} new boxes · open Sahl", asked));
      root.append(summary);
    }
    let askNo = first;
    for (const f of fields) {
      const target = targets.get(f.element_id);
      if (!target) continue;
      const ask = f.unknown && !f.told;
      if (ask) askNo++;
      let els, hits;
      if (target.kind === "date-parts") {
        els = hits = target.parts.map((p) => p.el);
      } else if (target.kind === "radio") {
        els = [target.box || target.options[0]?.el];
        hits = target.options.map((o) => o.el);
      } else {
        els = hits = [face(target.el)];
      }
      const live = els.filter((e) => e?.isConnected);
      const liveHits = hits.filter((e) => e?.isConnected);
      if (!live.length || !liveHits.length) continue;
      const node = document.createElement("div");
      node.className = ask ? "ring ask" : "ring";
      const mark = document.createElement("span");
      mark.className = ask ? "num" : "dot";
      if (ask) mark.textContent = String(askNo);
      node.append(mark);
      root.append(node);
      const ring = { id: f.element_id, els: live, node, label: f.label, ask, n: askNo };
      rings.push(ring);
      for (const el of live) byEl.set(el, ring);
      for (const el of liveHits) {
        byEl.set(el, ring);
        for (const label of el.labels || []) byEl.set(label, ring);
      }
    }
    if (!rings.length) return clear();
    const tip = document.createElement("div");
    tip.className = "tip";
    tip.style.display = "none";
    root.append(tip);
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
  // a custom dropdown (Select2, Chosen, ARIA combobox): typing only filters its list, so the matching entry is clicked too
  const customMenu = (el) => el instanceof HTMLInputElement && Boolean(
    el.matches('[role=combobox], [aria-haspopup=listbox], [aria-autocomplete]')
    || el.closest('.select2, .select2-container, .select2-dropdown, .chosen-container, .choices, .ui-selectmenu-menu, .dropdown, .bootstrap-select, [class*=select-box], [class*=selectbox]'));
  const OPTIONS = '[role=option], .select2-results__option, .chosen-results li, .choices__item--choice, .ui-menu-item, .dropdown-menu li, ul[role=listbox] li';
  const pickEntry = async (el, want) => {
    const w = norm(want);
    for (let tries = 0; tries < 12; tries++) {
      const hit = [...document.querySelectorAll(OPTIONS)].filter(shown2).find((o) => norm(text(o)) === w)
        || [...document.querySelectorAll(OPTIONS)].filter(shown2).find((o) => norm(text(o)).includes(w));
      if (hit) {
        for (const type of ["mouseover", "mousedown", "mouseup", "click"]) {
          hit.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, composed: true, view: window }));
        }
        return true;
      }
      await new Promise((done) => setTimeout(done, 100));
    }
    return false;
  };
  const shown2 = (o) => { const r = o.getBoundingClientRect(); return r.width >= 1 && r.height >= 1 && !o.classList.contains("select2-results__message"); };
  // a filled box's ring turns teal with a tick, one box after another, so the person sees each one go in
  const done = (id, ok) => rings.find((r) => r.id === id)?.node.classList.toggle("done", ok);
  const fill = async (values, replace) => {
    const pace = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 90;
    const results = [];
    for (const v of values) {
      const r = fillOne(v, replace);
      results.push(r);
      if (r.ok && !r.skipped) done(v.element_id, true);
      if (pace) await new Promise((next) => setTimeout(next, pace));
    }
    await new Promise((next) => setTimeout(next, 60));
    for (let i = 0; i < results.length; i++) {
      const result = results[i];
      const value = values[i];
      if (!result.ok || result.skipped) continue;
      const target = targets.get(value.element_id);
      if (!target || target.kind !== "text") continue;
      const want = String(value.value ?? "");
      if (customMenu(target.el)) {
        if (await pickEntry(target.el, want)) continue;
        result.ok = false;
        result.reason = "no matching option";
        done(value.element_id, false);
        continue;
      }
      if (String(target.el.value ?? "") === want) continue;
      typeText(target.el, want);
      await new Promise((next) => setTimeout(next, 30));
      if (String(target.el.value ?? "") !== want) {
        result.ok = false;
        result.reason = "the page did not keep the value";
        done(value.element_id, false);
      }
    }
    return results;
  };

  const enter = (e) => {
    const ring = byEl.get(e.target);
    if (!ring || ring === active) return;
    active = ring;
    schedule();
  };
  const leave = (e) => {
    if (!active || byEl.get(e.target) !== active) return;
    if (byEl.get(e.relatedTarget) === active) return;
    active = null;
    schedule();
  };
  addEventListener("pointerover", enter, { capture: true, passive: true });
  addEventListener("pointerout", leave, { capture: true, passive: true });
  addEventListener("focusin", enter, true);
  addEventListener("focusout", leave, true);
  addEventListener("scroll", schedule, { capture: true, passive: true });
  addEventListener("resize", schedule, { passive: true });
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    const type = String(msg?.type || "");
    const mine = (name) => type === `sahl:v${version}:${name}`;
    if (mine("scan")) { words = msg.strings || words; showReading(); reply(scan()); return true; }
    if (mine("read-end")) { if (reading) clear(); reply({ ok: true }); return true; }
    if (mine("render")) { words = msg.strings || words; reply(render(msg.fields || [], msg.asked, Number(msg.first) || 0)); return true; }
    if (mine("fill")) {
      fill(msg.values || [], Boolean(msg.replace)).then(reply, () => reply([]));
      return true;
    }
    if (mine("clear")) { clear(); reply({ ok: true }); return true; }
    return false;
  });
  addEventListener("pagehide", clear, { once: true });
})();
