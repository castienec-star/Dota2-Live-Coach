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
$$(".nav").forEach((b) => b.addEventListener("click", () => {
  if (!b.dataset.page) return;  // Replay review opens its own window
  show(b.dataset.page);
  if (b.dataset.page === "progress") progress().catch((err) => console.error(err));
}));

// Dashboard -------------------------------------------------------------

function render(status) {
  const state = !status.running ? "off" : status.connected ? "live" : "on";
  $("#ring").className = "ring " + state;
  $("#side-pill").className = "pill " + state;
  $("#side-state").textContent = t({ off: "Off", on: "Waiting for Dota", live: "Coaching" }[state]);
  $("#state-eyebrow").textContent = t({ off: "Coach off", on: "Coach running", live: "Live" }[state]);
  $("#headline").textContent = status.headline;
  $("#detail").textContent = status.problem || (status.last_said ? t("Last line: ") + status.last_said : "");
  const go = $("#go");
  go.textContent = t(status.running ? "Stop coach" : "Start coach");
  go.className = "btn big " + (status.running ? "stop" : "primary");
  $("#t-dota").textContent = t(status.connected ? "Connected" : status.running ? "Waiting" : "Not connected");
  if (status.version) $("#side-version").textContent = t("Version ") + status.version;
}

function addEvents(events) {
  const feed = $("#feed");
  for (const e of events) {
    if (e.kind === "said") linesSaid++;
    if (!SHOWN.has(e.kind) && !showDetails) continue;
    $(".empty", feed)?.remove();
    feed.append(el("li", { class: e.kind },
      el("span", { class: "t" }, e.time || ""),
      el("span", { class: "k" }, t(KIND[e.kind] || e.kind)),
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
  toast(t("Setting up Dota 2..."));
  const out = await api.set_up_dota();
  toast(out.ok ? t("Dota 2 is set up. Restart Dota if it is open.") : out.text, !out.ok);
});
$("#a-reviews").addEventListener("click", () => api.open_folder("reviews"));
$("#a-builds").addEventListener("click", () => api.open_builds());
$("#a-replay").addEventListener("click", () => api.open_replay());
$("#nav-replay").addEventListener("click", () => api.open_replay());

// Settings --------------------------------------------------------------

function dirty() { return JSON.stringify(current) !== JSON.stringify(saved); }
function changed() {
  $("#savebar").classList.toggle("show", dirty());
  $("#savebar").classList.remove("error");
  $("#save-msg").textContent = t("You have unsaved changes.");
  summary();
}
function summary() {
  const on = Object.values(current.reminders).filter(Boolean).length;
  const all = Object.keys(current.reminders).length;
  $("#count").textContent = t("{on} of {all} on", { on, all });
  $("#t-on").textContent = t("{on} of {all}", { on, all });
  $("#t-mode").textContent = t(current.mode === "experienced" ? "Experienced" : "Beginner");
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
      ? [["", t("Windows default")], ...voices.map((v) => [v, v]), ...(value && !voices.includes(value) ? [[value, value]] : [])]
      : f.choices;
    const sel = el("select", { class: "input", onchange: (e) => set(e.target.value) },
      opts.map(([k, label]) => el("option", { value: k, selected: String(value) === k }, label)));
    if (f.kind !== "voice") return sel;
    return el("div", { class: "row grow" }, sel,
      el("button", { class: "btn small", onclick: () => api.test_voice(current.fields["voice.name"], +current.fields["voice.rate"] || 0) }, t("Test")));
  }
  const input = el("input", { class: "input", value, inputmode: f.kind === "text" ? "text" : "numeric",
    oninput: (e) => set(e.target.value) });
  const unit = UNITS[f.kind] && t(UNITS[f.kind]);
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
          el("div", { class: "item-title" }, r.label, r.experienced ? el("span", { class: "badge" }, t("Essential")) : null),
          el("div", { class: "item-help" }, r.help)),
        r.fields.length ? el("button", { class: "more", onclick: () => item.classList.toggle("open") }, t("Timing"), chevron()) : null);
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
  drawGeneral("#general-voice", ["language", "voice", "listen"]);
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
  toast(t("Defaults restored. Save to keep them."));
});
$("#discard").addEventListener("click", () => { current = clone(saved); drawAll(); changed(); });
$("#save").addEventListener("click", async () => {
  const out = await api.save_settings(current);
  if (!out.ok) {
    $("#savebar").classList.add("error");
    $("#save-msg").textContent = out.errors.join(" · ");
    return;
  }
  if (out.language_changed) { location.reload(); return; }  // the whole page in the new language
  saved = out.values; current = clone(saved);
  drawAll(); changed();
  toast(t(out.restarted ? "Saved. The coach restarted with your settings." : "Saved. The coach uses them next time it starts."));
});

// Progress --------------------------------------------------------------

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs = {}) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}
const fmt = (n) => Number(n).toLocaleString(locale());
function niceStep(span) {
  const raw = span / 4, p = 10 ** Math.floor(Math.log10(raw || 1));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw);
}

function mmrChart(points) {
  const box = $("#mmr-chart");
  box.replaceChildren();
  if (!points.length) { box.append(el("div", { class: "chart-empty" }, t("Save your MMR to start your graph."))); return; }
  const W = 640, H = 240, L = 48, R = 56, T = 14, B = 28;
  const values = points.map((p) => p.mmr);
  let lo = Math.min(...values), hi = Math.max(...values);
  const pad = Math.max(50, (hi - lo) * 0.15); lo -= pad; hi += pad;
  const step = niceStep(hi - lo); lo = Math.max(0, Math.floor(lo / step) * step); hi = Math.ceil(hi / step) * step;
  const ts = points.map((p) => new Date(p.day + "T00:00:00").getTime());
  const t0 = ts[0], t1 = ts[ts.length - 1] === t0 ? t0 + 86400000 : ts[ts.length - 1];
  const x = (v) => points.length === 1 ? L + (W - L - R) / 2 : L + ((v - t0) / (t1 - t0)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": t("MMR over time") });
  for (let v = lo; v <= hi + 1e-9; v += step) {
    s.append(svg("line", { class: "grid", x1: L, x2: W - R, y1: y(v), y2: y(v) }));
    const lab = svg("text", { class: "axis", x: L - 8, y: y(v) + 4, "text-anchor": "end" });
    lab.textContent = fmt(v);
    s.append(lab);
  }
  const day = (i) => new Date(ts[i]).toLocaleDateString(locale(), { month: "short", day: "numeric" });
  const ticks = points.length <= 6 ? points.map((_, i) => i) : [0, Math.floor((points.length - 1) / 2), points.length - 1];
  for (const i of ticks) {
    const lab = svg("text", { class: "axis", x: x(ts[i]), y: H - 8, "text-anchor": "middle" });
    lab.textContent = day(i);
    s.append(lab);
  }
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(ts[i]).toFixed(1)},${y(p.mmr).toFixed(1)}`).join("");
  if (points.length > 1) {
    s.append(svg("path", { class: "area", d: `${path}L${x(ts[ts.length - 1])},${H - B}L${x(ts[0])},${H - B}Z` }));
    s.append(svg("path", { class: "line", d: path }));
  }
  const last = points.length - 1;
  s.append(svg("circle", { class: "pt", cx: x(ts[last]), cy: y(values[last]), r: 4.5 }));
  const end = svg("text", { class: "end-label", x: x(ts[last]) + 10, y: y(values[last]) + 4 });
  end.textContent = fmt(values[last]);
  s.append(end);
  // Hover: a crosshair and the nearest entry.
  const cross = svg("line", { class: "cross", y1: T, y2: H - B, visibility: "hidden" });
  const dot = svg("circle", { class: "pt", r: 5, visibility: "hidden" });
  s.append(cross, dot);
  const tip = el("div", { class: "tip", hidden: true });
  const hit = svg("rect", { class: "hit", x: L - 10, y: T, width: W - L - R + 20, height: H - T - B });
  hit.addEventListener("mousemove", (e) => {
    const r = s.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * W;
    let i = 0;
    ts.forEach((v, j) => { if (Math.abs(x(v) - px) < Math.abs(x(ts[i]) - px)) i = j; });
    const cx = x(ts[i]), cy = y(values[i]);
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("visibility", "visible");
    const change = i ? values[i] - values[i - 1] : null;
    tip.replaceChildren(el("b", {}, fmt(values[i]) + " MMR"), day(i) + (change == null ? "" : ` · ${change >= 0 ? "+" : ""}${change}`));
    tip.hidden = false;
    tip.style.left = (cx / W) * r.width + "px";
    tip.style.top = (cy / H) * r.height + "px";
  });
  hit.addEventListener("mouseleave", () => {
    tip.hidden = true; cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden");
  });
  s.append(hit);
  box.append(s, tip);
}

function heroChart(heroes) {
  const box = $("#hero-chart");
  box.replaceChildren();
  if (!heroes.length) {
    box.append(el("div", { class: "chart-empty" }, t("Play a match with the coach running and your heroes show up here.")));
    return;
  }
  const bars = el("div", { class: "bars", role: "list" });
  for (const h of heroes.slice(0, 12)) {
    const wr = h.win_rate;
    bars.append(el("div", { class: "bar-row", role: "listitem",
      title: t("{name}: {wins} wins, {losses} losses in {games} games · average K/D/A {kda}", h) },
      el("div", { class: "bar-name" }, h.name),
      el("div", { class: "bar-track" }, el("div", { class: "half" }),
        el("div", { class: "bar-fill", style: `width: ${wr ?? 0}%` })),
      el("div", { class: "bar-value" }, wr == null ? "-" : wr + "%",
        el("span", {}, `  ${h.wins}-${h.losses} · ${h.games} ${t(h.games === 1 ? "game" : "games")}`))));
  }
  box.append(bars);
}

function recs(list) {
  const box = $("#recs");
  box.replaceChildren();
  if (!list.length) {
    box.append(el("div", { class: "muted" }, t("Play a few games with the coach running and its recommendations show up here.")));
    return;
  }
  for (const r of list) {
    box.append(el("div", { class: "rec " + r.tone },
      el("div", { class: "ico", "aria-hidden": "true" }, r.tone === "good" ? "✓" : "!"),
      el("div", {}, el("b", {}, r.title), el("span", {}, r.text))));
  }
}

const METRICS = { deaths: "Deaths", last_hits_10: "Last hits at 10:00", gpm: "Gold per minute" };
let trendData = [], trendMetric = "deaths";

function trendChart() {
  const box = $("#trend-chart");
  box.replaceChildren();
  const games = trendData;
  if (!games.length) { box.append(el("div", { class: "chart-empty" }, t("No recorded games yet."))); return; }
  const W = 960, H = 220, L = 40, R = 10, T = 16, B = 34;
  const vals = games.map((g) => g[trendMetric]);
  const max = Math.max(1, ...vals.filter((v) => v != null));
  const step = niceStep(max), top = Math.ceil(max / step) * step;
  const y = (v) => T + (1 - v / top) * (H - T - B);
  const band = (W - L - R) / games.length, bar = Math.min(24, band * 0.6);
  const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": t("{metric} in the last games", { metric: t(METRICS[trendMetric]) }) });
  for (let v = 0; v <= top + 1e-9; v += step) {
    s.append(svg("line", { class: "grid", x1: L, x2: W - R, y1: y(v), y2: y(v) }));
    const lab = svg("text", { class: "axis", x: L - 8, y: y(v) + 4, "text-anchor": "end" });
    lab.textContent = fmt(v);
    s.append(lab);
  }
  const tip = el("div", { class: "tip", hidden: true });
  games.forEach((g, i) => {
    const v = g[trendMetric], cx = L + band * (i + 0.5);
    const h = v == null ? 3 : Math.max(2, y(0) - y(v));
    const r = Math.min(4, bar / 2, h);
    const x0 = cx - bar / 2, y0 = y(0) - h;
    // Rounded at the data end only, square on the baseline.
    const d = `M${x0},${y(0)}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}H${x0 + bar - r}Q${x0 + bar},${y0} ${x0 + bar},${y0 + r}V${y(0)}Z`;
    const col = svg("path", { class: "col" + (v == null ? " empty" : ""), d });
    const hit = svg("rect", { class: "col-hit", x: cx - band / 2, y: T, width: band, height: H - T - B });
    hit.addEventListener("mouseenter", () => {
      col.classList.add("hover");
      const result = t(g.won === true ? "Win" : g.won === false ? "Loss" : "Result unknown");
      tip.replaceChildren(el("b", {}, v == null ? "-" : `${fmt(v)} ${t(METRICS[trendMetric]).toLowerCase()}`), `${g.date} · ${result}`);
      const rect = s.getBoundingClientRect();
      tip.hidden = false;
      tip.style.left = (cx / W) * rect.width + "px";
      tip.style.top = (y0 / H) * rect.height + "px";
    });
    hit.addEventListener("mouseleave", () => { col.classList.remove("hover"); tip.hidden = true; });
    s.append(hit, col);
    if (g.won != null) {
      const wl = svg("text", { class: "wl " + (g.won ? "w" : "l"), x: cx, y: H - 18, "text-anchor": "middle" });
      wl.textContent = g.won ? "W" : "L";
      s.append(wl);
    }
  });
  for (const i of [0, games.length - 1]) {
    const lab = svg("text", { class: "axis", x: L + band * (i + 0.5), y: H - 4, "text-anchor": "middle" });
    lab.textContent = games[i].date;
    s.append(lab);
  }
  box.append(s, tip);
}
$$("#trend-metric button").forEach((b) => b.addEventListener("click", () => {
  trendMetric = b.dataset.metric;
  $$("#trend-metric button").forEach((x) => x.classList.toggle("active", x === b));
  trendChart();
}));

async function loadDetails(m, target, button) {
  button.disabled = true;
  button.textContent = t("Loading...");
  const out = await api.match_details(m.match_id, m.account_id);
  if (!out.ok) {
    target.replaceChildren(el("div", { class: "muted small" }, out.message));
    button.textContent = t("Try again");
    button.disabled = false;
    return;
  }
  button.remove();
  target.replaceChildren(
    out.stats.length ? el("div", { class: "kv" }, out.stats.map((s) => el("div", {}, el("span", {}, s.label), fmt(s.value)))) : "",
    out.ranks.length ? el("h3", {}, t("Against all games on this hero")) : "",
    ...out.ranks.map((r) => el("div", { class: "pct", title: t("Better than {pct}% of games on this hero", r) },
      el("span", {}, r.label), el("div", { class: "track" }, el("div", { class: "mid" }), el("div", { class: "fill", style: `width: ${r.pct}%` })),
      el("span", {}, r.pct + "%"))),
    out.tips.length ? el("h3", {}, t("What to work on")) : "",
    out.tips.length ? el("ul", { class: "notes" }, out.tips.map((x) => el("li", { class: /strength|fortaleza/.test(x) ? "good" : "" }, x))) : "");
}

function matchTable(rows) {
  const table = $("#matches");
  const head = ["Date", "Hero", "Result", "K/D/A", "LH/DN", "GPM", "XPM", "Length", ""].map((h) => t(h));
  table.replaceChildren(el("thead", {}, el("tr", {}, head.map((h) => el("th", {}, h)))));
  const body = el("tbody");
  if (!rows.length) body.append(el("tr", {}, el("td", { colspan: head.length, class: "muted" }, t("No recorded matches yet."))));
  for (const m of rows) {
    const row = el("tr", { class: "mrow" },
      el("td", {}, m.date), el("td", {}, m.hero),
      el("td", { class: m.result === "Win" ? "win" : m.result === "Loss" ? "loss" : "" }, t(m.result)),
      el("td", {}, m.kda), el("td", {}, m.last_hits), el("td", {}, String(m.gpm)), el("td", {}, String(m.xpm)),
      el("td", {}, m.duration),
      el("td", {}, m.link ? el("a", { onclick: (e) => { e.stopPropagation(); api.open_url(m.link); } }, "OpenDota") : ""));
    let detail = null;
    row.addEventListener("click", () => {
      if (detail) { detail.remove(); detail = null; row.classList.remove("open"); return; }
      row.classList.add("open");
      const od = el("div");
      const button = m.match_id && m.account_id
        ? el("button", { class: "btn small", onclick: () => loadDetails(m, od, button) }, t("Load OpenDota numbers")) : null;
      const facts = [
        m.last_hits_10 != null ? t("{n} last hits at 10:00", { n: m.last_hits_10 }) : null,
        m.deaths_early ? t(m.deaths_early === 1 ? "{n} death before 10:00" : "{n} deaths before 10:00", { n: m.deaths_early }) : null,
      ].filter(Boolean).join(" · ");
      detail = el("tr", { class: "detail" }, el("td", { colspan: head.length }, el("div", { class: "detail-grid detail" },
        el("div", {}, el("h3", {}, t("Coach's review")), facts ? el("div", { class: "muted small", style: "margin-bottom: 8px" }, facts) : "",
          el("ul", { class: "notes" }, m.notes.map((n) => el("li", { class: n.tone }, n.text)))),
        el("div", {}, el("h3", {}, "OpenDota"), od, button))));
      row.after(detail);
    });
    body.append(row);
  }
  table.append(body);
}

async function progress() {
  const p = await api.progress();
  const pts = p.mmr;
  const latest = pts.length ? pts[pts.length - 1] : null;
  $("#p-mmr").textContent = latest ? fmt(latest.mmr) + (p.medal ? ` · ${p.medal}` : "") : t("Not set");
  const diff = pts.length > 1 ? latest.mmr - pts[0].mmr : null;
  $("#p-change").textContent = diff == null ? "-" : (diff >= 0 ? "+" : "") + fmt(diff);
  $("#p-games").textContent = p.games;
  $("#p-wr").textContent = p.finished ? `${Math.round((100 * p.wins) / p.finished)}%  (${p.wins}-${p.finished - p.wins})` : "-";
  $("#mmr-sub").textContent = pts.length ? t(pts.length === 1 ? "{n} entry since {day}" : "{n} entries since {day}", { n: pts.length, day: pts[0].day }) : "";
  $("#mmr-banner").hidden = !p.mmr_due;
  $("#mmr-banner-text").textContent = latest
    ? t("Last updated {day}. Update it every {n} days to track your progress.", { day: latest.day, n: p.ask_every_days })
    : t("Enter it once and the coach won't ask your rank during games.");
  recs(p.recommendations);
  trendData = p.trend;
  mmrChart(pts); trendChart(); heroChart(p.heroes); matchTable(p.matches);
}

async function saveMmr(input, msg) {
  const out = await api.add_mmr($(input).value);
  if (msg) $(msg).textContent = out.message;
  toast(out.message, !out.ok);
  if (out.ok) { $(input).value = ""; await progress(); }
  if (out.mode_switched) {
    saved = out.values; current = clone(saved); drawAll();
    toast(out.mode_switched);
  }
}
$("#mmr-go").addEventListener("click", () => saveMmr("#mmr-input", "#mmr-msg"));
$("#mmr-quick-go").addEventListener("click", () => saveMmr("#mmr-quick"));
$("#mmr-input").addEventListener("keydown", (e) => { if (e.key === "Enter") saveMmr("#mmr-input", "#mmr-msg"); });
$("#mmr-quick").addEventListener("keydown", (e) => { if (e.key === "Enter") saveMmr("#mmr-quick"); });

// Licence ---------------------------------------------------------------

async function licence() {
  const state = await api.license_state();
  const ok = !state.required || state.ok;
  $("#lic-state").replaceChildren(
    el("span", { class: "dot", style: `background: var(${ok ? "--green" : "--amber"})` }),
    !state.required ? t("Free test build: no licence needed yet.") : ok ? t("Active on this PC.") : state.message);
  $("#gate").hidden = ok;
  $("#gate-msg").textContent = state.message || t("Enter your licence key to start.");
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
  translatePage(await api.language());
  await licence();
  const data = await api.load_settings();
  schema = data.schema; voices = data.voices;
  saved = data.values; current = clone(saved);
  drawAll();
  if (data.notice) toast(data.notice);
  await progress().catch((err) => console.error(err));
  await poll();
  polling = setInterval(poll, 400);
}

if (window.pywebview?.api) boot(window.pywebview.api);
else window.addEventListener("pywebviewready", () => boot(window.pywebview.api));
