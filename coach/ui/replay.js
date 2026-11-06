// The Replay review window. Python answers through pywebview's js_api
// (coach/replay_api.py): every call is `await api.<name>(...)`.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
let api = null, settings = null, running = false, lastSaid = "";
const KIND = { said: "Coach", skipped: "Late", connected: "Dota", match: "Match", problem: "Check", stopped: "Off", version: "App", log: "Note" };

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "class") node.className = v;
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

function chooseMode(mode) {
  settings.mode = mode;
  $$(".mode-card").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("#interval-field").hidden = mode !== "continuous";
}

async function checkModel() {
  $("#model-state").textContent = t("Checking...");
  const out = await api.check_model(settings.model);
  $("#model-state").textContent = out.text;
}

function render(out) {
  running = out.running;
  const state = !running ? "off" : out.following ? "live" : "on";
  $("#ring").className = "ring " + state;
  $("#eyebrow").textContent = t({ off: "Review off", on: "Waiting for a replay", live: "Reviewing" }[state]);
  $("#headline").textContent = state === "live" ? t("Reviewing your {hero}.", { hero: out.following }) : t({
    off: "Pick how the coach should look, then press Start review.",
    on: "Open one of your replays in Dota 2 (Watch > Replays).",
  }[state]);
  $("#detail").textContent = lastSaid ? t("Last: ") + lastSaid : "";
  const go = $("#go");
  go.textContent = t(running ? "Stop review" : "Start review");
  go.className = "btn big " + (running ? "stop" : "primary");
  $$("#modes button, #model, #interval, #hero").forEach((x) => (x.disabled = running));
}

function addEvents(events) {
  const feed = $("#feed");
  for (const e of events) {
    const note = e.kind === "log" && e.text.startsWith("following your hero");
    if (!note && !["said", "skipped", "problem", "stopped"].includes(e.kind)) continue;
    if (e.kind === "said") lastSaid = e.text;
    $(".empty", feed)?.remove();
    feed.append(el("li", { class: e.kind },
      el("span", { class: "t" }, e.time || ""),
      el("span", { class: "k" }, t(KIND[e.kind] || e.kind)),
      el("span", { class: "x" }, note ? t("following your hero {hero}", { hero: e.text.slice(20) }) : e.text)));
    while (feed.children.length > 400) feed.firstChild.remove();
    feed.scrollTop = feed.scrollHeight;
  }
}

async function poll() {
  try {
    const out = await api.poll();
    addEvents(out.events);
    render(out);
  } catch (err) { console.error(err); }
}

$("#go").addEventListener("click", async () => {
  const out = running ? await api.stop() : await api.start(settings);
  addEvents(out.events);
  render(out);
  if (out.running) toast(t("Review started. Open your replay in Dota 2."));
});
$$(".mode-card").forEach((b) => b.addEventListener("click", () => chooseMode(b.dataset.mode)));

async function boot(bridge) {
  api = bridge;
  const data = await api.load();
  settings = data.settings;
  translatePage(data.language);
  const model = $("#model");
  for (const m of data.models) model.append(el("option", { value: m.id, selected: m.id === settings.model }, m.label));
  if (!data.models.some((m) => m.id === settings.model)) model.append(el("option", { value: settings.model, selected: true }, settings.model));
  model.addEventListener("change", (e) => { settings.model = e.target.value; checkModel(); });
  const interval = $("#interval");
  for (const s of data.intervals) interval.append(el("option", { value: s, selected: +settings.interval === s }, t("{n} seconds", { n: s })));
  interval.addEventListener("change", (e) => (settings.interval = +e.target.value));
  const hero = $("#hero");
  for (const h of data.heroes) hero.append(el("option", { value: h.key, selected: h.key === settings.hero }, h.name));
  hero.addEventListener("change", (e) => (settings.hero = e.target.value));
  chooseMode(settings.mode);
  checkModel();
  await poll();
  setInterval(poll, 400);
}

if (window.pywebview?.api) boot(window.pywebview.api);
else window.addEventListener("pywebviewready", () => boot(window.pywebview.api));
