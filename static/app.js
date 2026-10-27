"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  coverType: "cover_blind",
  schema: null,
  options: {},
  environment: defaultEnv(),
  location: { lat: 0.0, lon: 0.0, elev: 0.0, tz: "UTC" },
  date: localDateStr(),
  timeMinutes: 720,
  curve: null,
};

let _simTimer = null;

function defaultEnv() {
  return {
    climate_mode_enabled: "auto",
    temp_switch: false,
    inside_temperature: 21,
    outside_temperature: null,
    is_presence: true,
    is_sunny: true,
    lux: null,
    irradiance: null,
    cloud_coverage: null,
    wind_speed: null,
    wind_direction: null,
    rain_rate: null,
    is_raining: false,
    is_windy: false,
    severe_active: false,
    manual_override_active: false,
    motion_timeout_active: false,
    motion_control_enabled: true,
    enable_sun_tracking: "auto",
    in_time_window: true,
    clock_window_open: true,
    current_cover_position: null,
    set_position: true,
    cloud_suppression_active: "auto",
    cloud_escalation_active: false,
    custom_position_active: {},
  };
}

function localDateStr(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function humanize(key) {
  let s = key.replace(/_/g, " ").trim();
  s = s.replace(/^(set|enable|disable|conf|use)_/, "");
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

const STORAGE_KEY = "acp-simulator-state";

function filteredOptions() {
  const out = {};
  for (const [k, v] of Object.entries(state.options)) {
    if (v === null || v === undefined || v === "") continue;
    out[k] = v;
  }
  return out;
}

function currentEnvelope() {
  return {
    home_assistant: { version: "simulator" },
    custom_components: {},
    integration_manifest: { domain: "adaptive_cover_pro" },
    data: {
      title: "Adaptive Cover Pro Configuration",
      type: "config_entry",
      config_data: { sensor_type: state.coverType, name: "Simulator" },
      config_options: filteredOptions(),
      diagnostics: {},
    },
  };
}

function saveState() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        v: 1,
        coverType: state.coverType,
        location: state.location,
        date: state.date,
        timeMinutes: state.timeMinutes,
        options: state.options,
        environment: state.environment,
      })
    );
  } catch (e) {
    /* ignore quota/security errors */
  }
}

function restoreState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || data.v !== 1) return null;
    if (data.coverType) state.coverType = data.coverType;
    if (data.location) state.location = { ...state.location, ...data.location };
    if (data.date) state.date = data.date;
    if (typeof data.timeMinutes === "number") state.timeMinutes = data.timeMinutes;
    if (data.environment) state.environment = { ...defaultEnv(), ...data.environment };
    return data.options || null;
  } catch (e) {
    return null;
  }
}

function syncHeaderInputs() {
  document.getElementById("lat").value = state.location.lat;
  document.getElementById("lon").value = state.location.lon;
  document.getElementById("elev").value = state.location.elev;
  document.getElementById("tz").value = state.location.tz;
  document.getElementById("date").value = state.date;
  document.getElementById("time").value = state.timeMinutes;
  updateTimeReadout();
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function init() {
  const restoredOptions = restoreState();
  syncHeaderInputs();
  bindHeader();
  bindImport();
  renderEntities();
  renderEnv();

  const { cover_types } = await api("/api/cover-types");
  state.supportedTypes = cover_types.map((ct) => ct.id);
  const select = document.getElementById("cover-type");
  select.innerHTML = "";
  for (const ct of cover_types) {
    const opt = document.createElement("option");
    opt.value = ct.id;
    opt.textContent = ct.label;
    select.appendChild(opt);
  }
  select.value = state.coverType;
  select.addEventListener("change", () => {
    state.coverType = select.value;
    loadSchema(null);
    saveState();
  });

  await loadSchema(restoredOptions);
  refreshSunCurve();
  scheduleSimulate();
}

function bindHeader() {
  for (const id of ["lat", "lon", "elev", "tz"]) {
    document.getElementById(id).addEventListener("input", () => {
      state.location.lat = parseFloat(document.getElementById("lat").value) || 0;
      state.location.lon = parseFloat(document.getElementById("lon").value) || 0;
      state.location.elev = parseFloat(document.getElementById("elev").value) || 0;
      state.location.tz = document.getElementById("tz").value || "UTC";
      refreshSunCurve();
      scheduleSimulate();
    });
  }
  document.getElementById("date").addEventListener("change", (e) => {
    state.date = e.target.value || localDateStr();
    refreshSunCurve();
    scheduleSimulate();
  });
  document.getElementById("time").addEventListener("input", (e) => {
    state.timeMinutes = parseInt(e.target.value, 10) || 0;
    updateTimeReadout();
    updateSunMarker();
    scheduleSimulate();
  });
}

// ---------------------------------------------------------------------------
// Schema / config form
// ---------------------------------------------------------------------------

async function loadSchema(restoredOptions) {
  state.schema = await api(`/api/schema?cover_type=${encodeURIComponent(state.coverType)}`);
  state.options = {};
  for (const section of state.schema.sections) {
    for (const f of section.fields) {
      if (f.default !== null && f.default !== undefined) {
        state.options[f.key] = f.default;
      }
    }
  }
  // Restored (persisted / imported) values take precedence over schema defaults.
  if (restoredOptions && typeof restoredOptions === "object") {
    Object.assign(state.options, restoredOptions);
  }
  renderSchema();
  scheduleSimulate();
}

function renderSchema() {
  const root = document.getElementById("schema");
  root.innerHTML = "";
  if (!state.schema) return;

  const openSections = new Set(["geometry", "sun_tracking", "position"]);

  for (const section of state.schema.sections) {
    const det = document.createElement("details");
    det.open = openSections.has(section.name);
    const summary = document.createElement("summary");
    summary.textContent = `${section.title} (${section.fields.length})`;
    det.appendChild(summary);

    if (section.description) {
      const desc = document.createElement("p");
      desc.className = "section-desc";
      desc.textContent = stripMarkdown(section.description);
      det.appendChild(desc);
    }

    const grid = document.createElement("div");
    grid.className = "field-grid";
    for (const f of section.fields) {
      grid.appendChild(renderField(f));
    }
    det.appendChild(grid);
    root.appendChild(det);
  }
}

function stripMarkdown(s) {
  return String(s || "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\[(.+?)\]\((.+?)\)/g, "$1")
    .replace(/`(.+?)`/g, "$1")
    .replace(/^#{1,6}\s*/gm, "");
}

function renderField(f) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  if (f.control === "boolean") wrap.classList.add("boolean");

  const label = document.createElement("label");
  label.textContent = f.label || humanize(f.key);
  label.title = f.key + (f.description ? "\n\n" + stripMarkdown(f.description) : "");
  if (f.description) label.classList.add("has-desc");

  if (f.control === "boolean") {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = !!state.options[f.key];
    input.addEventListener("change", () => {
      state.options[f.key] = input.checked;
      scheduleSimulate();
    });
    wrap.appendChild(label);
    wrap.appendChild(input);
    return wrap;
  }

  wrap.appendChild(label);

  if (f.control === "number") {
    const input = document.createElement("input");
    input.type = "number";
    if (f.step != null) input.step = f.step;
    if (f.min != null) input.min = f.min;
    if (f.max != null) input.max = f.max;
    input.value = state.options[f.key] ?? "";
    if (f.unit) input.title = `unit: ${f.unit}`;
    input.addEventListener("input", () => {
      state.options[f.key] = input.value === "" ? null : parseFloat(input.value);
      scheduleSimulate();
    });
    wrap.appendChild(input);
    return wrap;
  }

  if (f.control === "select") {
    const opts = f.options || [];
    const cur = state.options[f.key];

    if (f.multiple && !f.custom_value) {
      // Checkbox chips for a small, fixed set of choices.
      const chips = document.createElement("div");
      chips.className = "chips";
      const values = opts.map((o) => o.value);
      const sel = new Set(cur == null ? values : Array.isArray(cur) ? cur : [cur]);
      const boxes = [];
      for (const o of opts) {
        const lab = document.createElement("label");
        lab.className = "chip-option";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = sel.has(o.value);
        const span = document.createElement("span");
        span.textContent = o.label;
        lab.appendChild(cb);
        lab.appendChild(span);
        boxes.push({ cb, value: o.value });
        chips.appendChild(lab);
      }
      const sync = () => {
        const chosen = boxes.filter((b) => b.cb.checked).map((b) => b.value);
        state.options[f.key] =
          chosen.length === values.length ? null : chosen.length === 0 ? [] : chosen;
        scheduleSimulate();
      };
      boxes.forEach((b) => b.cb.addEventListener("change", sync));
      wrap.appendChild(chips);
      return wrap;
    }

    if (f.multiple) {
      // custom_value multi-select → comma-separated text.
      const input = document.createElement("input");
      input.type = "text";
      input.value = Array.isArray(cur) ? cur.join(",") : (cur ?? "");
      input.placeholder = "comma-separated";
      input.addEventListener("input", () => {
        const raw = input.value.trim();
        state.options[f.key] = raw === "" ? null : raw.split(",").map((s) => s.trim());
        scheduleSimulate();
      });
      wrap.appendChild(input);
      return wrap;
    }

    const input = document.createElement("select");
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "—";
    input.appendChild(empty);
    for (const o of opts) {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = o.label;
      input.appendChild(opt);
    }
    input.value = cur ?? "";
    input.addEventListener("change", () => {
      state.options[f.key] = input.value === "" ? null : input.value;
      scheduleSimulate();
    });
    wrap.appendChild(input);
    return wrap;
  }

  if (f.control === "template" || f.control === "entity") {
    const input = document.createElement("textarea");
    input.rows = f.control === "template" ? 3 : 1;
    input.value = state.options[f.key] ?? "";
    input.placeholder = f.control === "template" ? "{{ ... }}" : "sensor.example";
    input.addEventListener("input", () => {
      state.options[f.key] = input.value.trim() === "" ? null : input.value;
      scheduleSimulate();
    });
    wrap.appendChild(input);
    return wrap;
  }

  // text / time / duration / fallback
  const input = document.createElement("input");
  input.type = "text";
  input.value = state.options[f.key] ?? "";
  input.addEventListener("input", () => {
    state.options[f.key] = input.value.trim() === "" ? null : input.value;
    scheduleSimulate();
  });
  wrap.appendChild(input);
  return wrap;
}

// ---------------------------------------------------------------------------
// Entities panel (simulated entity state/value inputs)
// ---------------------------------------------------------------------------

const ENTITY_GROUPS = [
  {
    title: "Climate & light",
    fields: [
      ["inside_temperature", "Inside temperature (°C)", "num", ["temp_entity"]],
      ["outside_temperature", "Outside temperature (°C)", "num", ["outside_temp", "weather_entity"]],
      ["is_presence", "Presence", "bool", ["presence_entity"]],
      ["is_sunny", "Is sunny", "bool", ["is_sunny_sensor", "weather_entity"]],
      ["lux", "Lux", "num", ["lux_entity"]],
      ["irradiance", "Irradiance (W/m²)", "num", ["irradiance_entity"]],
      ["cloud_coverage", "Cloud coverage (%)", "num", ["cloud_coverage_entity"]],
    ],
  },
  {
    title: "Weather",
    fields: [
      ["wind_speed", "Wind speed", "num", ["weather_wind_speed_sensor"]],
      ["wind_direction", "Wind direction (°)", "num", ["weather_wind_direction_sensor"]],
      ["rain_rate", "Rain rate", "num", ["weather_rain_sensor"]],
      ["is_raining", "Is raining", "bool", ["weather_is_raining_sensor"]],
      ["is_windy", "Is windy", "bool", ["weather_is_windy_sensor"]],
      ["severe_active", "Severe weather", "bool", ["weather_severe_sensors"]],
    ],
  },
];

const ENV_GROUPS = [
  {
    title: "Runtime state",
    fields: [
      ["climate_mode_enabled", "Climate mode switch", "tri"],
      ["temp_switch", "Use outside temp", "bool"],
      ["manual_override_active", "Manual override", "bool"],
      ["motion_timeout_active", "Motion timeout", "bool"],
      ["motion_control_enabled", "Motion control enabled", "bool"],
      ["enable_sun_tracking", "Sun tracking", "tri"],
      ["in_time_window", "In time window", "bool"],
      ["clock_window_open", "Clock window open", "bool"],
      ["cloud_suppression_active", "Cloud suppression", "tri"],
      ["cloud_escalation_active", "Cloud escalation", "bool"],
      ["current_cover_position", "Current position (%)", "num"],
      ["set_position", "Supports set_position", "bool"],
    ],
  },
  {
    title: "Custom position slots",
    fields: [1, 2, 3, 4, 5].map((n) => [`cp${n}`, `Slot ${n} active`, "bool"]),
  },
];

function entitySource(sources) {
  if (!sources) return null;
  for (const key of sources) {
    const v = state.options[key];
    if (Array.isArray(v) && v.length) return v.join(", ");
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

function renderEntities() {
  const root = document.getElementById("entities");
  root.innerHTML = "";
  for (const group of ENTITY_GROUPS) {
    const g = document.createElement("div");
    g.className = "env-group";
    const title = document.createElement("div");
    title.className = "env-title";
    title.textContent = group.title;
    g.appendChild(title);
    for (const [key, label, kind, sources] of group.fields) {
      g.appendChild(renderEntityRow(key, label, kind, entitySource(sources)));
    }
    root.appendChild(g);
  }
}

function renderEntityRow(key, label, kind, source) {
  const row = document.createElement("div");
  row.className = "env-row entity";

  const labWrap = document.createElement("div");
  labWrap.className = "env-label";
  const lab = document.createElement("label");
  lab.textContent = label;
  labWrap.appendChild(lab);
  const hint = document.createElement("div");
  hint.className = "hint" + (source ? "" : " off");
  hint.textContent = source || "— no sensor configured —";
  labWrap.appendChild(hint);
  row.appendChild(labWrap);

  const input = document.createElement(kind === "bool" ? "input" : "input");
  if (kind === "bool") {
    input.type = "checkbox";
    input.checked = !!state.environment[key];
    input.addEventListener("change", () => {
      state.environment[key] = input.checked;
      scheduleSimulate();
    });
  } else {
    input.type = "number";
    input.value = state.environment[key] ?? "";
    input.addEventListener("input", () => {
      state.environment[key] = input.value === "" ? null : parseFloat(input.value);
      scheduleSimulate();
    });
  }
  row.appendChild(input);
  return row;
}

function renderEnv() {
  const root = document.getElementById("env");
  root.innerHTML = "";
  for (const group of ENV_GROUPS) {
    const g = document.createElement("div");
    g.className = "env-group";
    const title = document.createElement("div");
    title.className = "env-title";
    title.textContent = group.title;
    g.appendChild(title);
    for (const [key, label, kind] of group.fields) {
      g.appendChild(renderEnvRow(key, label, kind));
    }
    root.appendChild(g);
  }
}

function renderEnvRow(key, label, kind) {
  const row = document.createElement("div");
  row.className = "env-row";
  const lab = document.createElement("label");
  lab.textContent = label;

  const input = document.createElement(kind === "bool" ? "input" : kind === "num" ? "input" : "select");

  if (kind === "bool") {
    input.type = "checkbox";
    input.checked = key.startsWith("cp")
      ? !!state.environment.custom_position_active[key]
      : !!state.environment[key];
    input.addEventListener("change", () => {
      if (key.startsWith("cp")) state.environment.custom_position_active[key] = input.checked;
      else state.environment[key] = input.checked;
      scheduleSimulate();
    });
  } else if (kind === "num") {
    input.type = "number";
    input.value = state.environment[key] ?? "";
    input.addEventListener("input", () => {
      state.environment[key] = input.value === "" ? null : parseFloat(input.value);
      scheduleSimulate();
    });
  } else if (kind === "tri") {
    input.innerHTML = "";
    for (const [v, l] of [["auto", "auto"], ["on", "on"], ["off", "off"]]) {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = l;
      input.appendChild(o);
    }
    input.value = state.environment[key] ?? "auto";
    input.addEventListener("change", () => {
      state.environment[key] = input.value;
      scheduleSimulate();
    });
  }

  row.appendChild(lab);
  row.appendChild(input);
  return row;
}

// ---------------------------------------------------------------------------
// Import diagnostics
// ---------------------------------------------------------------------------

function bindImport() {
  const box = document.getElementById("import-box");
  document.getElementById("import-btn").addEventListener("click", () => box.classList.toggle("hidden"));
  document.getElementById("import-cancel").addEventListener("click", () => box.classList.add("hidden"));

  const exportBtn = document.getElementById("export-btn");
  exportBtn.addEventListener("click", () => {
    const text = JSON.stringify(currentEnvelope(), null, 2);
    navigator.clipboard.writeText(text).then(() => {
      const old = exportBtn.textContent;
      exportBtn.textContent = "Copied ✓";
      setTimeout(() => (exportBtn.textContent = old), 1200);
    });
  });

  document.getElementById("import-run").addEventListener("click", async () => {
    const raw = document.getElementById("import-json").value.trim();
    if (!raw) return;
    try {
      const json = JSON.parse(raw);
      const result = await api("/api/import-diagnostics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ json }),
      });
      if (!result.cover_type && !result.options) {
        alert("No config found. Expected a Home Assistant diagnostics file for an Adaptive Cover Pro cover (config_data.sensor_type + config_options).");
        return;
      }
      if (result.cover_type) {
        if (state.supportedTypes && !state.supportedTypes.includes(result.cover_type)) {
          alert(`Cover type "${result.cover_type}" isn't supported by the simulator yet (supported: blind, awning, tilt).`);
          return;
        }
        state.coverType = result.cover_type;
        document.getElementById("cover-type").value = result.cover_type;
      }
      state.options = result.options || {};
      for (const [k, v] of Object.entries(result.environment || {})) {
        if (k in state.environment) state.environment[k] = v;
      }
      renderSchema();
      renderEntities();
      renderEnv();
      box.classList.add("hidden");
      scheduleSimulate();
    } catch (e) {
      alert("Could not parse diagnostics JSON: " + e.message);
    }
  });
}

// ---------------------------------------------------------------------------
// Simulate
// ---------------------------------------------------------------------------

function buildPayload() {
  const options = filteredOptions();
  const env = { ...state.environment };
  if (env.enable_sun_tracking === "auto") env.enable_sun_tracking = null;
  else env.enable_sun_tracking = env.enable_sun_tracking === "on";
  if (env.cloud_suppression_active === "auto") env.cloud_suppression_active = null;
  else env.cloud_suppression_active = env.cloud_suppression_active === "on";
  if (env.climate_mode_enabled === "auto") env.climate_mode_enabled = null;
  else env.climate_mode_enabled = env.climate_mode_enabled === "on";

  return {
    cover_type: state.coverType,
    options,
    environment: env,
    location: state.location,
    date: state.date,
    time_minutes: state.timeMinutes,
  };
}

function scheduleSimulate() {
  if (_simTimer) clearTimeout(_simTimer);
  _simTimer = setTimeout(() => {
    saveState();
    simulate();
  }, 250);
}

async function simulate() {
  try {
    const result = await api("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload()),
    });
    document.getElementById("sun-az").textContent = result.sun.azimuth.toFixed(1);
    document.getElementById("sun-alt").textContent = result.sun.elevation.toFixed(1);
    renderResult(result);
  } catch (e) {
    renderError(e);
  }
}

function renderError(e) {
  document.getElementById("result").innerHTML = `<div class="error">${escapeHtml(e.message)}</div>`;
}

function renderResult(r) {
  const root = document.getElementById("result");
  const method = r.result.control_method;
  const tilt = r.result.tilt != null ? r.result.tilt : "—";

  const validityChips = [
    r.cover.valid ? "sun in FOV" : "sun outside",
    r.cover.direct_sun_valid ? "direct sun" : "no direct sun",
  ]
    .map((t) => `<span class="chip ${t === "sun in FOV" ? "on" : ""}">${t}</span>`)
    .join(" ");

  const extras = [];
  if (r.weather_override_active) extras.push(`<span class="chip warn">weather override</span>`);
  if (r.cloud_suppression_active) extras.push(`<span class="chip warn">cloud suppression</span>`);
  if (r.climate_extreme_heat_active) extras.push(`<span class="chip warn">extreme heat</span>`);

  root.innerHTML = `
    <div class="result-hero">
      <div class="position">${r.result.position}<small> %</small></div>
      <div><span class="k">Control method</span></div>
      <div class="method">${method}</div>
      <div><span class="k">Tilt</span></div>
      <div>${tilt}</div>
      <div><span class="k">Sun</span></div>
      <div>az ${r.sun.azimuth.toFixed(1)}° · alt ${r.sun.elevation.toFixed(1)}° · γ ${r.cover.gamma ?? "—"}°</div>
      <div><span class="k">Validity</span></div>
      <div>${validityChips} ${extras.join(" ")}</div>
    </div>
    <div class="reason">${escapeHtml(r.position_explanation || r.result.reason || "")}</div>
    <h3>Decision trace</h3>
    <table class="trace">
      <thead><tr><th>handler</th><th>priority</th><th>position</th><th>reason</th></tr></thead>
      <tbody>
        ${r.result.decision_trace
          .map(
            (s) => `<tr class="${s.matched ? "winner" : "muted"}">
              <td>${escapeHtml(s.handler)}${s.matched ? " ✓" : ""}</td>
              <td>${s.priority ?? ""}</td>
              <td>${s.position ?? "—"}</td>
              <td>${escapeHtml(s.reason || "")}</td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table>
    <details class="diag">
      <summary>Full diagnostics JSON <button id="copy-json" onclick="event.stopPropagation(); copyDiag()">Copy</button></summary>
      <pre class="json">${escapeHtml(JSON.stringify(r.diagnostics, null, 2))}</pre>
    </details>
  `;
  window._lastDiag = r.diagnostics;
}

function copyDiag() {
  if (window._lastDiag == null) return;
  navigator.clipboard.writeText(JSON.stringify(window._lastDiag, null, 2));
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ---------------------------------------------------------------------------
// Sun path diagram
// ---------------------------------------------------------------------------

function updateTimeReadout() {
  const h = String(Math.floor(state.timeMinutes / 60)).padStart(2, "0");
  const m = String(state.timeMinutes % 60).padStart(2, "0");
  document.getElementById("time-readout").textContent = `${h}:${m}`;
}

async function refreshSunCurve() {
  try {
    const c = await api(
      `/api/sun-curve?lat=${state.location.lat}&lon=${state.location.lon}&elev=${state.location.elev}&tz=${encodeURIComponent(state.location.tz)}&date=${state.date}`
    );
    state.curve = c;
    drawSunCurve();
    updateSunMarker();
  } catch (e) {
    state.curve = null;
  }
}

function drawSunCurve() {
  const svg = document.getElementById("sunpath");
  const c = state.curve;
  if (!c) return;
  const W = 720;
  const H = 140;
  const pad = 12;
  const yMin = -20;
  const yMax = 90;
  const y = (el) => pad + ((yMax - el) / (yMax - yMin)) * (H - 2 * pad);

  const n = c.times.length;
  const x = (i) => pad + (i / (n - 1)) * (W - 2 * pad);

  let pts = "";
  for (let i = 0; i < n; i++) pts += `${x(i).toFixed(1)},${y(c.elevation[i]).toFixed(1)} `;

  const toMin = (t) => {
    const [hh, mm] = t.split(":").map(Number);
    return hh * 60 + mm;
  };
  const sunriseIdx = Math.round((toMin(c.sunrise) / 1440) * (n - 1));
  const sunsetIdx = Math.round((toMin(c.sunset) / 1440) * (n - 1));

  svg.innerHTML = `
    <rect x="0" y="0" width="${W}" height="${H}" fill="#0d1117"/>
    <line x1="${pad}" y1="${y(0)}" x2="${W - pad}" y2="${y(0)}" stroke="#2a333f" stroke-width="1"/>
    <line x1="${x(sunriseIdx)}" y1="${pad}" x2="${x(sunriseIdx)}" y2="${H - pad}" stroke="#f2b04a" stroke-width="1" stroke-dasharray="3 3"/>
    <line x1="${x(sunsetIdx)}" y1="${pad}" x2="${x(sunsetIdx)}" y2="${H - pad}" stroke="#f2b04a" stroke-width="1" stroke-dasharray="3 3"/>
    <text x="${x(sunriseIdx) + 4}" y="${pad + 8}" fill="#f2b04a" font-size="10">${c.sunrise}</text>
    <text x="${x(sunsetIdx) - 40}" y="${pad + 8}" fill="#f2b04a" font-size="10">${c.sunset}</text>
    <polyline points="${pts}" fill="none" stroke="#4da3ff" stroke-width="2"/>
    <g id="sun-marker"></g>
  `;
}

function updateSunMarker() {
  const svg = document.getElementById("sunpath");
  const g = svg && svg.querySelector("#sun-marker");
  const c = state.curve;
  if (!g || !c) return;
  const W = 720;
  const H = 140;
  const pad = 12;
  const yMin = -20;
  const yMax = 90;
  const y = (el) => pad + ((yMax - el) / (yMax - yMin)) * (H - 2 * pad);
  const n = c.times.length;
  const idx = Math.round((state.timeMinutes / 1440) * (n - 1));
  const x = pad + (idx / (n - 1)) * (W - 2 * pad);
  const el = c.elevation[idx] ?? 0;
  g.innerHTML = `<circle cx="${x.toFixed(1)}" cy="${y(el).toFixed(1)}" r="5" fill="#ffd166"/>`;
}

init();
