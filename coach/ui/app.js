// The app window's page. Python answers through pywebview's js_api
// (coach/app_api.py): every call is `await api.<name>(...)`.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
let api = null;
let schema = null, saved = null, current = null, voices = [];
let showDetails = false, linesSaid = 0, polling = null;

const UNITS = { seconds: "sec", minute: "min", percent: "%", clock: "m:ss" };
const SHOWN = new Set(["said", "skipped", "connected", "match", "problem", "stopped"]);
const KIND = { said: "Coach", skipped: "Late", connected: "Dota", match: "Match", problem: "Check", stopped: "Off", version: "App", log: "Log" };

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) node.append(kid.nodeType ? kid : document.createTextNode(kid));
  return node;
}

function toast(text, warn = false) {
  const t = $("#toast");
  t.textContent = text;
  t.className = "toast show" + (warn ? " warn" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.className = "toast"), 3200);
}

const clone = (v) => JSON.parse(JSON.stringify(v));

// Navigation ------------------------------------------------------------

function show(page) {
  $$(".nav").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + page));
  $("main").scrollTop = 0;
}
$$(".nav").forEach((b) => b.addEventListener("click", () => show(b.dataset.page)));

// Dashboard -------------------------------------------------------------

function render(status) {
  const state = !status.running ? "off" : status.connected ? "live" : "on";
  $("#ring").className = "ring " + state;
  $("#side-pill").className = "pill " + state;
  $("#side-state").textContent = { off: "Off", on: "Waiting for Dota", live: "Coaching" }[state];
  $("#state-eyebrow").textContent = { off: "Coach off", on: "Coach running", live: "Live" }[state];
  $("#headline").textContent = status.headline;
  $("#detail").textContent = status.problem || (status.last_said ? "Last line: " + status.last_said : "");
  const go = $("#go");
  go.textContent = status.running ? "Stop coach" : "Start coach";
  go.className = "btn big " + (status.running ? "stop" : "primary");
  $("#t-dota").textContent = status.connected ? "Connected" : status.running ? "Waiting" : "Not connected";
  if (status.version) $("#side-version").textContent = "Version " + status.version;
}

function addEvents(events) {
  const feed = $("#feed");
  for (const e of events) {
    if (e.kind === "said") linesSaid++;
    if (!SHOWN.has(e.kind) && !showDetails) continue;
    $(".empty", feed)?.remove();
    feed.append(el("li", { class: e.kind },
      el("span", { class: "t" }, e.time || ""),
      el("span", { class: "k" }, KIND[e.kind] || e.kind),
      el("span", { class: "x" }, e.text)));
    while (feed.children.length > 400) feed.firstChild.remove();
    feed.scrollTop = feed.scrollHeight;
  }
  $("#t-lines").textContent = linesSaid;
}

async function poll() {
  try {
    const out = await api.poll();
    addEvents(out.events);
    render(out.status);
  } catch (err) { console.error(err); }
}

$("#go").addEventListener("click", async () => {
  const out = await api.poll();
  render((out.status.running ? await api.stop() : await api.start()).status);
});
$("#details").addEventListener("change", (e) => (showDetails = e.target.checked));
$("#a-setup").addEventListener("click", async () => {
  toast("Setting up Dota 2...");
  const out = await api.set_up_dota();
  toast(out.ok ? "Dota 2 is set up. Restart Dota if it is open." : out.text, !out.ok);
});
$("#a-reviews").addEventListener("click", () => api.open_folder("reviews"));
$("#a-builds").addEventListener("click", () => api.open_builds());

// Settings --------------------------------------------------------------

function dirty() { return JSON.stringify(current) !== JSON.stringify(saved); }
function changed() {
  $("#savebar").classList.toggle("show", dirty());
  $("#savebar").classList.remove("error");
  $("#save-msg").textContent = "You have unsaved changes.";
  summary();
}
function summary() {
  const on = Object.values(current.reminders).filter(Boolean).length;
  const all = Object.keys(current.reminders).length;
  $("#count").textContent = `${on} of ${all} on`;
  $("#t-on").textContent = `${on} of ${all}`;
  $("#t-mode").textContent = current.mode === "experienced" ? "Experienced" : "Beginner";
  $$("#mode button").forEach((b) => b.classList.toggle("active", b.dataset.mode === current.mode));
}

function switchEl(checked, onchange, label) {
  return el("label", { class: "switch", title: label },
    el("input", { type: "checkbox", checked, "aria-label": label, onchange }), el("span"));
}

function control(f) {
  const value = current.fields[f.path];
  const set = (v) => { current.fields[f.path] = v; changed(); };
  if (f.kind === "toggle") return switchEl(!!value, (e) => set(e.target.checked), f.label);
  if (f.kind === "choice" || f.kind === "voice") {
    const opts = f.kind === "voice"
      ? [["", "Windows default"], ...voices.map((v) => [v, v]), ...(value && !voices.includes(value) ? [[value, value]] : [])]
      : f.choices;
    const sel = el("select", { class: "input", onchange: (e) => set(e.target.value) },
      opts.map(([k, label]) => el("option", { value: k, selected: String(value) === k }, label)));
    if (f.kind !== "voice") return sel;
    return el("div", { class: "row grow" }, sel,
      el("button", { class: "btn small", onclick: () => api.test_voice(current.fields["voice.name"], +current.fields["voice.rate"] || 0) }, "Test"));
  }
  const input = el("input", { class: "input", value, inputmode: f.kind === "text" ? "text" : "numeric",
    oninput: (e) => set(e.target.value) });
  const unit = UNITS[f.kind];
  return unit ? el("div", { class: "unit" }, input, el("em", {}, unit)) : input;
}

function field(f) {
  return el("div", { class: "field", "data-path": f.path },
    el("label", { class: "field-label" }, f.label), control(f),
    f.help ? el("div", { class: "hint" }, f.help) : null);
}

const chevron = () => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 12 12");
  s.innerHTML = '<path d="M2 4l4 4 4-4"/>';
  return s;
};

function drawReminders() {
  const root = $("#groups");
  root.replaceChildren();
  for (const g of schema.reminders) {
    const list = el("div", { class: "list" });
    for (const r of g.reminders) {
      const on = !!current.reminders[r.name];
      const item = el("div", { class: "item" + (on ? "" : " off"), "data-name": r.name,
        "data-search": (r.label + " " + r.help + " " + g.title).toLowerCase() });
      const main = el("div", { class: "item-main" },
        switchEl(on, (e) => { current.reminders[r.name] = e.target.checked; item.classList.toggle("off", !e.target.checked); changed(); }, r.label),
        el("div", { class: "item-text" },
          el("div", { class: "item-title" }, r.label, r.experienced ? el("span", { class: "badge" }, "Essential") : null),
          el("div", { class: "item-help" }, r.help)),
        r.fields.length ? el("button", { class: "more", onclick: () => item.classList.toggle("open") }, "Timing", chevron()) : null);
      item.append(main);
      if (r.fields.length) item.append(el("div", { class: "fields" }, r.fields.map(field)));
      list.append(item);
    }
    root.append(el("div", { class: "group", "data-group": g.id },
      el("div", { class: "group-head" }, el("h2", {}, g.title), el("span", { class: "muted small" }, g.help)), list));
  }
  filter();
}

function drawGeneral(target, ids) {
  const root = $(target);
  root.replaceChildren();
  for (const g of schema.general.filter((g) => ids.includes(g.id))) {
    const list = el("div", { class: "list settings-list" });
    for (const f of g.fields) {
      list.append(el("div", { class: "item", "data-path": f.path }, el("div", { class: "item-main" },
        el("div", { class: "item-text" }, el("div", { class: "item-title" }, f.label),
          f.help ? el("div", { class: "item-help" }, f.help) : null),
        f.kind === "toggle" ? control(f) : el("div", { class: "control" }, control(f)))));
    }
    root.append(el("div", { class: "group" },
      el("div", { class: "group-head" }, el("h2", {}, g.title), el("span", { class: "muted small" }, g.help)), list));
  }
}

function drawAll() {
  drawReminders();
  drawGeneral("#general-voice", ["voice", "listen"]);
  drawGeneral("#general-game", ["game"]);
  summary();
}

function filter() {
  const q = $("#search").value.trim().toLowerCase();
  $$("#groups .item").forEach((i) => (i.hidden = q && !i.dataset.search.includes(q)));
  $$("#groups .group").forEach((g) => (g.hidden = $$(".item", g).every((i) => i.hidden)));
}
$("#search").addEventListener("input", filter);

$$("#mode button").forEach((b) => b.addEventListener("click", async () => {
  if (b.dataset.mode === current.mode) return;
  current = await api.switch_mode(current, b.dataset.mode);
  drawAll(); changed();
}));
function setAll(on) {
  for (const k of Object.keys(current.reminders)) current.reminders[k] = on;
  drawReminders(); changed();
}
$("#all-on").addEventListener("click", () => setAll(true));
$("#all-off").addEventListener("click", () => setAll(false));
$("#reset").addEventListener("click", async () => {
  current = await api.reset_settings(current.mode);
  drawAll(); changed();
  toast("Defaults restored. Save to keep them.");
});
$("#discard").addEventListener("click", () => { current = clone(saved); drawAll(); changed(); });
$("#save").addEventListener("click", async () => {
  const out = await api.save_settings(current);
  if (!out.ok) {
    $("#savebar").classList.add("error");
    $("#save-msg").textContent = out.errors.join(" · ");
    return;
  }
  saved = out.values; current = clone(saved);
  drawAll(); changed();
  toast(out.restarted ? "Saved. The coach restarted with your settings." : "Saved. The coach uses them next time it starts.");
});

// Licence ---------------------------------------------------------------

async function licence() {
  const state = await api.license_state();
  const ok = !state.required || state.ok;
  $("#lic-state").replaceChildren(
    el("span", { class: "dot", style: `background: var(${ok ? "--green" : "--amber"})` }),
    !state.required ? "Free test build: no licence needed yet." : ok ? "Active on this PC." : state.message);
  $("#gate").hidden = ok;
  $("#gate-msg").textContent = state.message || "Enter your licence key to start.";
  const buy = () => state.store && api.open_url(state.store);
  $("#lic-buy").onclick = buy; $("#gate-buy").onclick = buy;
  $("#lic-buy").hidden = $("#gate-buy").hidden = !state.store;
  return ok;
}
async function activate(input, msg) {
  const out = await api.activate($(input).value);
  $(msg).textContent = out.message;
  if (out.ok) { toast(out.message); await licence(); }
}
$("#gate-go").addEventListener("click", () => activate("#gate-key", "#gate-msg"));
$("#lic-go").addEventListener("click", () => activate("#lic-key", "#lic-msg"));

// Start -----------------------------------------------------------------

async function boot(bridge) {
  api = bridge;
  await licence();
  const data = await api.load_settings();
  schema = data.schema; voices = data.voices;
  saved = data.values; current = clone(saved);
  drawAll();
  await poll();
  polling = setInterval(poll, 400);
}

if (window.pywebview?.api) boot(window.pywebview.api);
else window.addEventListener("pywebviewready", () => boot(window.pywebview.api));
