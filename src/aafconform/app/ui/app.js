/* aafconform desktop interface.
 *
 * Talks to Python through window.pywebview.api in the desktop app, or through
 * POST /api/<name> when served by the development server. Every call returns
 * {ok, data} or {ok: false, error}. Text from AAF files is always escaped.
 */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const plural = (n, word, many) => `${n} ${n === 1 ? word : many || word + "s"}`;

/* ---------- bridge ---------- */

let pyReady = null;
function bridgeReady() {
  if (window.AAFCONFORM_DEV) return Promise.resolve("dev");
  if (window.pywebview && window.pywebview.api && window.pywebview.api.describe) return Promise.resolve("py");
  if (!pyReady) {
    pyReady = new Promise((resolve) => window.addEventListener("pywebviewready", () => resolve("py"), { once: true }));
  }
  return pyReady;
}

async function call(name, ...args) {
  const mode = await bridgeReady();
  try {
    if (mode === "py") return (await window.pywebview.api[name](...args)) || { ok: false, error: "No response" };
    const resp = await fetch("/api/" + name, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ args }),
    });
    return await resp.json();
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e) };
  }
}

/* ---------- state ---------- */

const S = {
  screen: "start",
  files: { reference: null, cut: null }, // {path, info}
  errors: { reference: "", cut: "" },
  loading: { reference: false, cut: false },
  hot: null,
  preview: null,
  previewError: "",
  pin: "auto",
  output: "",
  csv: true,
  json: false,
  conformError: "",
  result: null,
  filter: "all",
  sel: null,
};

const ZONES = {
  reference: {
    num: "01",
    lab: "Master layout",
    labColor: "var(--sand)",
    title: "Drop the master sequence AAF",
    desc: "The sequence on the episode's template, with each track playing the right multigroup channel.",
  },
  cut: {
    num: "02",
    lab: "Pull · to fix",
    labColor: "var(--bone)",
    title: "Drop the pull AAF",
    desc: "The cut made on the wrong template. Its edits, effects and L and J cuts are kept.",
  },
};

const STATUS = {
  kept: { label: "Kept", color: "var(--sand)", lane: "rgba(201,184,154,.5)", tint: "rgba(201,184,154,.1)", edge: "rgba(201,184,154,.35)" },
  built: { label: "Built", color: "var(--info)", lane: "rgba(56,175,232,.5)", tint: "rgba(56,175,232,.1)", edge: "rgba(56,175,232,.4)" },
  corrected: { label: "Corrected", color: "var(--success)", lane: "#5ad88a", tint: "rgba(90,216,138,.1)", edge: "rgba(90,216,138,.4)" },
  flagged: { label: "Needs attention", color: "var(--accent)", lane: "#e8a838", tint: "rgba(232,168,56,.1)", edge: "rgba(232,168,56,.45)" },
  "kept-other": { label: "Other material", color: "var(--muted)", lane: "#3a3a3e", tint: "rgba(155,152,147,.08)", edge: "#3a3a3e" },
  filler: { label: "Filler", color: "var(--subtle)", lane: "#232326", tint: "rgba(155,152,147,.06)", edge: "#2a2a2e" },
  transition: { label: "Dissolve", color: "var(--subtle)", lane: "#232326", tint: "rgba(155,152,147,.06)", edge: "#2a2a2e" },
};

const ICON = {
  check: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#5ad88a" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>',
  warn: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 3 2 20h20z"/><line x1="12" y1="10" x2="12" y2="14"/><line x1="12" y1="17" x2="12" y2="17"/></svg>',
  info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#38afe8" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><line x1="12" y1="8" x2="12" y2="8"/></svg>',
  folder: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  doc: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/></svg>',
  arrow: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  lock: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  layout: '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 4v5M13 4v5"/><path d="M7 14h4M7 17h7"/></svg>',
  cut: '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12"/></svg>',
};

/* ---------- helpers ---------- */

function tc(frame, fps, drop) {
  if (drop) {
    const d = Math.round(fps / 15);
    const per10 = fps * 600 - d * 9;
    const perMin = fps * 60 - d;
    const tens = Math.floor(frame / per10);
    const rem = frame % per10;
    frame += d * 9 * tens + (rem > d ? d * Math.floor((rem - d) / perMin) : 0);
  }
  const ff = frame % fps;
  const s = Math.floor(frame / fps);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor(s / 60) % 60)}:${p(s % 60)}${drop ? ";" : ":"}${p(ff)}`;
}

function busy(text) {
  $("#busy-text").textContent = text || "Working…";
  $("#busy").hidden = !text;
}

function show(screen) {
  S.screen = screen;
  for (const name of ["start", "check", "report"]) $("#screen-" + name).hidden = name !== screen;
  const order = ["start", "check", "report"];
  const reach = { start: true, check: !!S.preview, report: !!S.result };
  document.querySelectorAll(".steps button").forEach((b) => {
    const step = b.dataset.step;
    b.classList.toggle("on", step === screen);
    b.classList.toggle("done", step !== screen && reach[step]);
    b.disabled = !reach[step] || step === screen;
    b.setAttribute("aria-current", step === screen ? "step" : "false");
  });
  void order;
  window.scrollTo(0, 0);
}

/* ---------- 01 load ---------- */

function zoneHtml(kind) {
  const z = ZONES[kind];
  const f = S.files[kind];
  const icon = kind === "reference" ? ICON.layout : ICON.cut;
  const lab = `<span class="lab" style="color:${z.labColor}">${z.num} · ${esc(z.lab)}</span>`;
  if (S.loading[kind]) {
    return `<div class="well">${icon}</div>${lab}<div class="title">Reading…</div><span class="spin" aria-hidden="true"></span>`;
  }
  if (f) {
    const seq = f.info.sequence;
    const audio = seq.sound.length;
    return `<div class="well" style="color:var(--accent)">${icon}</div>${lab}
      <div class="title">${esc(seq.name)}</div>
      <div class="file" title="${esc(f.path)}">${esc(f.path)}</div>
      <div class="mono" style="font-size:11px;color:var(--muted)">${seq.fps} fps · ${esc(seq.duration)} · ${plural(seq.picture.length, "picture track")} · ${plural(audio, "audio track")}</div>
      <div class="row"><button class="btn" type="button" data-choose="${kind}">Replace…</button></div>`;
  }
  const err = S.errors[kind] ? `<div class="err" role="alert">${esc(S.errors[kind])}</div>` : "";
  return `<div class="well" style="color:${S.hot === kind ? "var(--accent)" : "var(--muted)"}">${icon}</div>${lab}
    <div class="title">${esc(z.title)}</div>
    <p class="desc">${esc(z.desc)}</p>${err}
    <div class="row"><button class="btn" type="button" data-choose="${kind}">Choose file… <span class="kk">Ctrl O</span></button></div>`;
}

function renderStart() {
  for (const kind of ["reference", "cut"]) {
    const el = $("#drop-" + kind);
    el.innerHTML = zoneHtml(kind);
    el.classList.toggle("hot", S.hot === kind);
    el.classList.toggle("loaded", !!S.files[kind]);
    el.classList.toggle("bad", !!S.errors[kind] && !S.files[kind]);
  }
}

async function choose(kind) {
  const r = await call("choose_file", kind === "reference" ? "Choose the master sequence AAF" : "Choose the pull AAF");
  if (!r.ok) {
    S.errors[kind] = r.error;
    renderStart();
    return;
  }
  if (r.data) await load(kind, r.data);
}

async function load(kind, path) {
  S.loading[kind] = true;
  S.errors[kind] = "";
  renderStart();
  const r = await call("describe", path);
  S.loading[kind] = false;
  if (!r.ok) {
    S.files[kind] = null;
    S.errors[kind] = r.error;
  } else if (!r.data.sequence) {
    S.files[kind] = null;
    const n = r.data.sequences.length;
    S.errors[kind] = n
      ? `This AAF holds ${n} sequences. Export just the one sequence from Media Composer.`
      : "There's no sequence in this AAF.";
  } else {
    S.files[kind] = { path, info: r.data };
  }
  const other = kind === "reference" ? "cut" : "reference";
  if (S.files[kind] && S.files[other] && S.files[kind].path === S.files[other].path) {
    S.files[kind] = null;
    S.errors[kind] = "That's the same file as the other one.";
  }
  if (kind === "cut" && S.files.cut) {
    const out = await call("default_output", path);
    S.output = out.ok ? out.data : "";
  }
  S.preview = null;
  S.result = null;
  renderStart();
  show("start");
  if (S.files.reference && S.files.cut) await runPreview();
}

async function runPreview() {
  busy("Reading both sequences…");
  const r = await call("preview", S.files.reference.path, S.files.cut.path, S.pin);
  busy("");
  S.previewError = r.ok ? "" : r.error;
  S.preview = r.ok ? r.data : null;
  S.conformError = "";
  renderCheck();
  show("check");
}

/* ---------- 02 check ---------- */

function chips(seq) {
  const v = seq.picture.map((t) => `<span class="ch ch-v">${esc(t.label)}</span>`);
  const a = seq.sound.map(
    (t) => `<span class="ch ${t.empty ? "ch-off" : "ch-on"}">${esc(t.label)}${t.name ? " " + esc(t.name) : ""}</span>`
  );
  return `<div class="chips">${v.join("")}${a.join("")}</div>`;
}

function fileCard(kind, extra) {
  const f = S.files[kind];
  const seq = f.info.sequence;
  const isRef = kind === "reference";
  const events = (() => {
    const t = seq.sound.find((x) => x.multigroup_events > 0) || seq.picture[0] || seq.sound[0];
    return t ? t.events : 0;
  })();
  return `<section class="card" aria-label="${isRef ? "Master layout" : "Pull"}">
    <header><span class="lab" style="color:${isRef ? "var(--sand)" : "var(--bone)"}">${isRef ? "Master layout" : "Pull · to fix"}</span>
      <div class="spacer"></div><button class="btn ghost" type="button" data-replace="${kind}" style="height:28px">Replace</button></header>
    <div class="body">
      <div><div class="name">${esc(seq.name)}</div><div class="path">${esc(f.path)}</div></div>
      <dl class="facts">
        <div><dt>Rate</dt><dd>${seq.fps} fps</dd></div>
        <div><dt>Start</dt><dd>${esc(seq.start)}</dd></div>
        <div><dt>Length</dt><dd>${esc(seq.duration)}</dd></div>
        <div><dt>${isRef ? "Multigroups" : "Events"}</dt><dd>${isRef ? seq.groups.length : events}</dd></div>
      </dl>
      ${chips(seq)}
      ${extra || ""}
    </div></section>`;
}

/* Consecutive built tracks read as one row: "A3–A8". */
function groupedPlan(tracks) {
  const rows = [];
  for (const t of tracks) {
    const last = rows[rows.length - 1];
    if (t.mode === "build" && last && last.mode === "build" && last.flagged === 0 && t.flagged === 0) {
      last.group.push(t);
      continue;
    }
    rows.push({ ...t, group: [t] });
  }
  return rows;
}

function whatHappens(t, p) {
  const ok = (n, s) => (n ? ` <span class="c-ok">${s}</span>` : "");
  const warn = t.flagged ? ` <span class="c-warn">${plural(t.flagged, "needs", "need")} attention.</span>` : "";
  const effects = p.effects.filter((e) => e.track === t.label).length;
  if (t.mode === "build") {
    const pin = esc(p.pin.replace(/'/g, ""));
    const diss = t.dissolves ? ` ${plural(t.dissolves, "dissolve")} copied; gain and pan are not.` : "";
    const many = t.group.length > 1 ? " Each on its own channel of the multigroup." : "";
    return `Built on ${pin}'s edits, so L and J cuts stay.${diss}${many}${warn}`;
  }
  if (t.mode === "extra") return "Not in the master layout, so carried over unchanged after its tracks.";
  const base = t.kind === "picture" ? "Kept as cut, every camera angle as chosen." : "Kept as you left it, gain and dissolves included.";
  const fx = effects ? ` ${plural(effects, "effect")} kept.` : "";
  return `${base}${ok(t.corrected, plural(t.corrected, "clip") + " used outside the multigroup swapped back in.")}${fx}${warn}`;
}

function renderCheck() {
  const el = $("#screen-check");
  const p = S.preview;
  if (!p) {
    el.innerHTML = `<div class="titlerow"><div><h1>Couldn't plan this conform</h1></div></div>
      <div class="note note-error" role="alert">${esc(S.previewError)}</div>
      <div><button class="btn" type="button" data-go="start">Back to the files</button></div>`;
    return;
  }
  const built = p.tracks.filter((t) => t.mode === "build");
  const missing = built.length
    ? `<span class="warnline">${ICON.warn} ${plural(built.length, "track")} of the master layout missing here · they'll be built</span>`
    : "";
  const rows = groupedPlan(p.tracks).map((t) => {
    const g = t.group;
    const label = g.length > 1 ? `${g[0].label}–${g[g.length - 1].label}` : t.label;
    const name = g.length > 1 ? g.map((x) => x.name || "–").join(", ") : t.name || (t.kind === "picture" ? "Picture" : "–");
    const modeLabel = { repair: "Kept", build: "Built", extra: "Carried" }[t.mode];
    const count = t.kept + t.built + t.corrected + t.other + t.flagged;
    return `<div class="plan">
      <span class="out" style="color:${t.kind === "picture" ? "var(--sand)" : "var(--fg)"}">${esc(label)}</span>
      <span class="tname">${esc(name)}</span>
      <span><span class="mode m-${t.mode}">${modeLabel}</span></span>
      <span class="what">${whatHappens(t, p)}</span>
      <span class="num">${count}${g.length > 1 ? " each" : ""}</span></div>`;
  });
  if (p.dropped.length) {
    rows.push(`<div class="plan" style="min-height:42px"><span></span><span class="mono" style="font-size:11px;color:var(--subtle)">Left out</span><span></span>
      <span class="what" style="color:var(--muted);font-size:12px">The pull's empty ${p.dropped.length === 1 ? "track" : "tracks"} ${esc(p.dropped.join(", "))}.</span><span></span></div>`);
  }
  const flagged = p.events.filter((e) => e.status === "flagged");
  const attention = flagged.length
    ? `<section class="card note-warn attn" aria-label="Needs attention"><span class="c-warn" style="margin-top:2px">${ICON.warn}</span>
        <div style="flex:1 1 420px;min-width:0"><b style="font-size:14px">${plural(flagged.length, "event")} will be left as ${flagged.length === 1 ? "it is" : "they are"}</b>
        <ul>${flagged
          .slice(0, 6)
          .map((e) => `<li><span class="mono" style="color:var(--fg)">${esc(e.track)} ${esc(e.name)} · ${esc(e.record_in)}</span> ${esc(e.note)}</li>`)
          .join("")}${flagged.length > 6 ? `<li>…and ${flagged.length - 6} more, listed in the report.</li>` : ""}</ul></div></section>`
    : "";
  const warnings = p.warnings.map((w) => `<div class="note note-warn">${esc(w)}</div>`).join("");
  const pins = S.files.cut.info.sequence.sound.filter((t) => t.multigroup_events > 0);
  const pinOptions =
    `<option value="auto"${S.pin === "auto" ? " selected" : ""}>${esc(p.pin.replace(/'/g, ""))} (automatic)</option>` +
    pins.map((t) => `<option value="${esc(t.label)}"${S.pin === t.label ? " selected" : ""}>${esc(t.label)} ${esc(t.name)}</option>`).join("");
  const totals = p.totals;
  const err = S.conformError ? `<div class="note note-error" role="alert">${esc(S.conformError)}</div>` : "";

  el.innerHTML = `
    <div class="titlerow"><div><h1>Here's what will happen</h1><p class="sub">Nothing is written until you press Conform. Both AAFs are only read.</p></div>
      <span class="lock">${ICON.lock} Runs on this machine · inputs never modified</span></div>
    <div class="files">${fileCard("reference")}${fileCard("cut", missing)}</div>
    <section class="card" aria-label="Track plan">
      <header><h2>Track plan</h2><span style="font-size:13px;color:var(--muted)">The master layout's tracks, with the pull's edits</span></header>
      <div class="plan-scroll"><div class="plan-grid">
        <div class="plan head"><span class="lab">Out</span><span class="lab">Track</span><span class="lab">From pull</span><span class="lab">What happens</span><span class="lab" style="text-align:right">Events</span></div>
        ${rows.join("")}
      </div></div>
    </section>
    ${warnings}${attention}
    <section class="card" aria-label="Output">
      <div class="outrow">
        <div class="field" style="flex:2 1 420px"><label class="lab" for="out">New AAF</label>
          <div style="display:flex;gap:8px"><input id="out" class="in" style="flex:1" value="${esc(S.output)}" spellcheck="false"><button class="btn" type="button" id="change-out">Change…</button></div></div>
        <div class="field" style="flex:1 1 220px"><label class="lab" for="pin">Edit points for new tracks</label><select id="pin" class="in">${pinOptions}</select></div>
        <div style="display:flex;gap:18px;height:32px;align-items:center">
          <label class="check"><input type="checkbox" id="csv"${S.csv ? " checked" : ""}>Report CSV</label>
          <label class="check"><input type="checkbox" id="json"${S.json ? " checked" : ""}>Report JSON</label></div>
      </div>
      ${err ? `<div style="padding:0 18px 16px">${err}</div>` : ""}
      <div class="bar"><div class="counts">
          <span><b>${built.length}</b> ${built.length === 1 ? "track" : "tracks"} to build</span>
          <span><b class="c-ok">${totals.corrected}</b> to correct</span>
          <span><b>${totals.effects}</b> ${totals.effects === 1 ? "effect" : "effects"} kept</span>
          <span><b class="${totals.flagged ? "c-warn" : ""}">${totals.flagged}</b> ${totals.flagged === 1 ? "needs" : "need"} attention</span></div>
        <div class="spacer"></div>
        <span class="mono" style="font-size:11px;color:var(--subtle);display:inline-flex;gap:4px"><span class="kk">Ctrl</span><span class="kk">↵</span></span>
        <button class="primary" type="button" id="conform">Conform ${ICON.arrow}</button></div>
    </section>`;
}

async function conform() {
  const output = ($("#out") && $("#out").value.trim()) || S.output;
  S.output = output;
  if (!output.toLowerCase().endsWith(".aaf")) {
    S.conformError = "The new file's name should end in .aaf.";
    renderCheck();
    return;
  }
  let replace = false;
  const exists = await call("output_exists", output);
  if (exists.ok && exists.data) {
    replace = window.confirm(`${output}\n\nalready exists. Replace it?`);
    if (!replace) return;
  }
  busy("Conforming…");
  const r = await call("conform", S.files.reference.path, S.files.cut.path, output, S.pin, S.csv, S.json, replace);
  busy("");
  if (!r.ok) {
    S.conformError = r.error;
    renderCheck();
    return;
  }
  S.result = r.data;
  S.filter = "all";
  const evs = r.data.events;
  const first = evs.findIndex((e) => e.status === "flagged");
  const corr = evs.findIndex((e) => e.status === "corrected");
  S.sel = first >= 0 ? first : corr >= 0 ? corr : 0;
  renderReport();
  show("report");
}

/* ---------- 03 report ---------- */

const trackName = (e) => e.name || (e.track.startsWith("V") ? "Picture" : "–");

function happened(e) {
  if (e.note) return e.note;
  const fx = effectsFor(e);
  return fx.length ? `${e.group} · ${fx.join(", ")} kept` : e.group || "";
}

function effectsFor(e) {
  const hit = S.result.effects.find((x) => x.track === e.track && x.record_in === e.record_in);
  return hit ? hit.effects : [];
}

function filtered() {
  const evs = S.result.events.map((e, i) => ({ e, i })).filter(({ e }) => e.status !== "transition");
  if (S.filter === "attn") return evs.filter(({ e }) => e.status === "flagged");
  if (S.filter === "corrected") return evs.filter(({ e }) => e.status === "corrected");
  if (S.filter === "effects") return evs.filter(({ e }) => effectsFor(e).length);
  return evs;
}

function ticks(length, fps, start, drop) {
  const minutes = length / fps / 60;
  const step = minutes <= 2 ? 0.25 : minutes <= 12 ? 2 : minutes <= 30 ? 5 : 10;
  const out = [];
  for (let m = 0; m <= minutes + 1e-9; m += step) {
    out.push({ left: ((m * 60 * fps) / length) * 100, label: tc(start + Math.round(m * 60 * fps), fps, drop).slice(0, 8) });
  }
  return out.filter((t) => t.left <= 96);
}

function renderReport() {
  const el = $("#screen-report");
  const r = S.result;
  const { fps, drop, start } = r.timecode;
  const len = Math.max(r.length, 1);
  const sel = r.events[S.sel] || null;
  const selKey = sel ? `${sel.track}|${sel.record_in}` : "";

  const laneLabels = r.lanes.map((l) => `<span title="${esc(l.label + " " + l.name)}">${esc(l.label)}${l.name ? " " + esc(l.name) : ""}</span>`).join("");
  const lanes = r.lanes
    .map((l) => {
      const items = l.items
        .map(([s, n, st]) => {
          const meta = STATUS[st] || STATUS.kept;
          const isSel = selKey === `${l.label}|${tc(start + s, fps, drop)}`;
          return `<i class="${isSel ? "sel" : ""}" style="left:${(s / len) * 100}%;width:${(n / len) * 100}%;background:${meta.lane}"></i>`;
        })
        .join("");
      return `<div class="lane">${items}</div>`;
    })
    .join("");
  const pinEvents = r.events
    .map((e, i) => ({ e, i }))
    .filter(({ e }) => e.status === "flagged" || e.status === "corrected")
    .slice(0, 24);
  const pins = pinEvents
    .map(({ e, i }) => {
      const lane = r.lanes.find((l) => l.label === e.track);
      const item = lane && lane.items.find(([s]) => tc(start + s, fps, drop) === e.record_in);
      if (!item) return "";
      const left = ((item[0] + item[1] / 2) / len) * 100;
      return `<button type="button" class="pin" data-sel="${i}" style="left:${left}%;background:${STATUS[e.status].lane}" aria-label="${esc(e.track + " at " + e.record_in + ", " + STATUS[e.status].label)}">${esc(e.track)}</button>`;
    })
    .join("");
  const tickHtml = ticks(len, fps, start, drop)
    .map((t) => `<span style="left:${t.left}%">${t.label}</span>`)
    .join("");

  const counts = {
    all: r.events.filter((e) => e.status !== "transition").length,
    attn: r.totals.flagged,
    corrected: r.totals.corrected,
    effects: r.totals.effects,
  };
  const tabs = [
    ["all", "All"],
    ["attn", "Needs attention"],
    ["corrected", "Corrected"],
    ["effects", "Effects kept"],
  ]
    .map(([k, label]) => `<button type="button" role="tab" class="${S.filter === k ? "on" : ""}" aria-selected="${S.filter === k}" data-filter="${k}">${label} <span style="opacity:.75">${counts[k]}</span></button>`)
    .join("");
  const list = filtered();
  const rows = list
    .map(({ e, i }) => {
      const m = STATUS[e.status] || STATUS.kept;
      return `<button type="button" class="trow${i === S.sel ? " sel" : ""}" data-sel="${i}" aria-pressed="${i === S.sel}">
        <span class="cell" style="color:var(--sand)">${esc(e.track)}</span><span class="cell">${esc(trackName(e))}</span>
        <span class="cell" style="color:var(--muted)">${esc(e.record_in)} – ${esc(e.record_out)}</span>
        <span class="cell" style="display:flex;align-items:center;gap:8px"><span class="dot" style="background:${m.color}"></span>${m.label}</span>
        <span class="cell note-text">${esc(happened(e))}</span></button>`;
    })
    .join("");

  let detail = `<div class="body"><p style="color:var(--muted);margin:0">Select an event.</p></div>`;
  if (sel) {
    const m = STATUS[sel.status] || STATUS.kept;
    const fx = effectsFor(sel);
    detail = `<header><span class="lab">${esc(sel.track)} · ${esc(trackName(sel))}</span><div class="spacer"></div>
        <span class="status-pill" style="background:${m.tint};color:${m.color}"><span class="dot" style="background:${m.color}"></span>${m.label}</span></header>
      <div class="body">
        <div><div class="tc">${esc(sel.record_in)}</div><div class="mono" style="font-size:11px;color:var(--subtle);margin-top:4px">Record in · out ${esc(sel.record_out)} · ${sel.frames} frames</div></div>
        <div class="chain">
          <div><span>Multigroup</span><span style="color:var(--sand)">${esc(sel.group || "–")}</span></div>
          <div><span>Group frame</span><span>${sel.group_pos ?? "–"}</span></div>
          <div><span>Channel</span><span>${sel.channel ?? "–"}</span></div>
          <div><span>Effects</span><span>${fx.length ? esc(fx.join(", ")) + " (kept)" : "None"}</span></div>
        </div>
        ${sel.note ? `<div class="note" style="background:${m.tint};border:1px solid ${m.edge}">${esc(sel.note)}</div>` : ""}
      </div>`;
  }

  const t = r.totals;
  el.innerHTML = `
    <section class="card banner"><span class="ok">${ICON.check}</span>
      <div class="what"><b>Conformed sequence written and checked</b>
        <div class="mono">${esc(r.output)} · sequence '${esc(r.sequence)}' · ${tc(len, fps, drop)}</div></div>
      <button class="btn" type="button" id="reveal">${ICON.folder} Show in Explorer</button>
      ${r.csv ? `<button class="btn" type="button" id="open-csv">${ICON.doc} Open report CSV</button>` : ""}
      <button class="btn ghost" type="button" id="another">Conform another pull</button></section>
    <div class="note note-info" style="display:flex;gap:12px;align-items:flex-start">${ICON.info}
      <div><b>Importing into Media Composer:</b> if it asks about a <span class="mono" style="font-size:12px">Group clip conflict</span>, choose <b>No</b> (or <b>No To All</b>). The new sequence uses the multigroup already in your project.</div></div>
    <div class="tiles">
      <div class="card tile"><span class="lab"><span class="dot" style="background:var(--sand)"></span>Kept as cut</span><span class="big">${t.kept}</span></div>
      <div class="card tile"><span class="lab"><span class="dot" style="background:var(--info)"></span>Built</span><span class="big">${t.built}</span></div>
      <div class="card tile"><span class="lab"><span class="dot" style="background:var(--success)"></span>Corrected</span><span class="big" style="color:var(--success)">${t.corrected}</span></div>
      <div class="card tile"><span class="lab">Effects kept</span><span class="big">${t.effects}</span></div>
      <div class="card tile"><span class="lab"><span class="dot" style="background:var(--accent)"></span>Needs attention</span><span class="big" style="color:${t.flagged ? "var(--accent)" : "var(--fg)"}">${t.flagged}</span></div>
    </div>
    <section class="card lanes" aria-label="Tracks">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h2 style="font-size:14px">The new sequence, track by track</h2><div class="spacer"></div>
        <div class="legend"><span><span class="dot" style="background:${STATUS.kept.lane}"></span>Kept</span><span><span class="dot" style="background:${STATUS.built.lane}"></span>Built</span>
        <span><span class="dot" style="background:${STATUS.corrected.lane}"></span>Corrected</span><span><span class="dot" style="background:${STATUS.flagged.lane}"></span>Needs attention</span>
        <span><span class="dot" style="background:${STATUS["kept-other"].lane}"></span>Other material</span></div></div>
      <div class="lanewrap"><div class="lanelabels">${laneLabels}</div>
        <div class="lanearea"><div class="pins">${pins}</div>${lanes}<div class="ticks">${tickHtml}</div></div></div>
    </section>
    <div class="split">
      <section class="card events" aria-label="Events">
        <div class="tools"><div class="seg" role="tablist" aria-label="Filter events">${tabs}</div></div>
        <div class="table"><div class="thead"><span class="lab">Track</span><span class="lab">Name</span><span class="lab">Record in – out</span><span class="lab">Result</span><span class="lab">What happened</span></div>${rows ||
          `<div style="padding:18px;color:var(--muted)">Nothing here.</div>`}</div>
        <div class="foot">${plural(list.length, "event")}${S.filter === "all" ? " · the CSV report has the same list" : ""}</div>
      </section>
      <aside class="card detail" aria-label="Event detail">${detail}</aside>
    </div>`;
}

/* ---------- events ---------- */

function onClick(e) {
  const t = e.target.closest("button, [data-choose], [data-replace], [data-go]");
  if (!t) return;
  if (t.dataset.choose) return choose(t.dataset.choose);
  if (t.dataset.replace) {
    show("start");
    return choose(t.dataset.replace);
  }
  if (t.dataset.go) return show(t.dataset.go);
  if (t.dataset.step && !t.disabled) {
    if (t.dataset.step === "check") renderCheck();
    if (t.dataset.step === "report") renderReport();
    return show(t.dataset.step);
  }
  if (t.dataset.filter) {
    S.filter = t.dataset.filter;
    return renderReport();
  }
  if (t.dataset.sel !== undefined) {
    S.sel = Number(t.dataset.sel);
    return renderReport();
  }
  switch (t.id) {
    case "conform":
      return conform();
    case "change-out":
      return call("choose_output", ($("#out") && $("#out").value) || S.output).then((r) => {
        if (r.ok && r.data) {
          S.output = r.data;
          renderCheck();
        } else if (!r.ok) {
          S.conformError = r.error;
          renderCheck();
        }
      });
    case "reveal":
      return call("reveal", S.result.output);
    case "open-csv":
      return call("open_file", S.result.csv);
    case "another":
      S.files.cut = null;
      S.preview = null;
      S.result = null;
      S.pin = "auto";
      renderStart();
      return show("start");
  }
}

function onChange(e) {
  const t = e.target;
  if (t.id === "pin") {
    S.pin = t.value;
    return runPreview();
  }
  if (t.id === "csv") S.csv = t.checked;
  if (t.id === "json") S.json = t.checked;
  if (t.id === "out") S.output = t.value;
}

function wireDrops() {
  for (const kind of ["reference", "cut"]) {
    const el = $("#drop-" + kind);
    const enter = (ev) => {
      ev.preventDefault();
      if (S.hot !== kind) {
        S.hot = kind;
        renderStart();
      }
    };
    el.addEventListener("dragenter", enter);
    el.addEventListener("dragover", enter);
    el.addEventListener("dragleave", (ev) => {
      if (!el.contains(ev.relatedTarget)) {
        S.hot = null;
        renderStart();
      }
    });
    el.addEventListener("drop", (ev) => {
      ev.preventDefault();
      S.hot = null;
      renderStart();
      // The desktop app passes the real path to app.dropped(); a browser can't.
      if (window.AAFCONFORM_DEV) {
        S.errors[kind] = "Dropping files needs the desktop app. Use app.load() in development.";
        renderStart();
      }
    });
  }
  // Dropping outside a zone must not navigate the window to the file.
  window.addEventListener("dragover", (ev) => ev.preventDefault());
  window.addEventListener("drop", (ev) => ev.preventDefault());
}

function onKey(e) {
  const ctrl = e.ctrlKey || e.metaKey;
  if (ctrl && e.key.toLowerCase() === "o" && S.screen === "start") {
    e.preventDefault();
    return choose(S.files.reference ? "cut" : "reference");
  }
  if (ctrl && e.key === "Enter" && S.screen === "check" && S.preview) {
    e.preventDefault();
    return conform();
  }
}

window.app = {
  dropped: (kind, path) => load(kind, path),
  load: (kind, path) => load(kind, path),
  state: S,
};

document.addEventListener("click", onClick);
document.addEventListener("change", onChange);
document.addEventListener("keydown", onKey);
wireDrops();
renderStart();
show("start");
call("version").then((r) => {
  if (r.ok) $("#version").textContent = "v" + r.data;
});
