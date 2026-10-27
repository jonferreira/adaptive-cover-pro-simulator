# Adaptive Cover Pro Simulator

A local web UI for previewing how an [Adaptive Cover Pro](https://github.com/jrhubott/adaptive-cover-pro)
cover will behave — without a running Home Assistant, without waiting for the
sun to actually move, and without faking the weather.

The simulator runs the **real Adaptive Cover Pro engine** headlessly. It does
not reimplement any logic: it imports the integration's own cover-type policies,
pipeline handlers, position calculations and diagnostics builder. Whatever you
configure here is what the integration will compute, so you can tune geometry,
thresholds, seasons, climate and automation settings and immediately see the
result.

> The simulator only **reads and imports** Adaptive Cover Pro. It never modifies
> the integration, its files or a live Home Assistant instance.

---

## What it does

- **Time travel.** Pick any date and drag a time slider to move the sun through
  the day. A sun-path diagram shows azimuth and elevation for the selected
  instant, and every calculation uses that simulated moment.
- **Full configuration editor.** Every option the integration exposes is
  rendered from the integration's own schema — section titles, icons, labels,
  descriptions and selector options are read from the integration's
  `translations/en.json`, so the UI matches the Home Assistant config flow.
- **Entities and environment in separate panels.** Set the values the cover
  would read from Home Assistant (weather, indoor/outdoor temperature, lux,
  climate state, …) and see how the pipeline reacts.
- **Decision trace and diagnostics.** The Result panel shows the computed
  position, the branch that produced it, and the same diagnostics payload Home
  Assistant produces — useful for understanding *why* a cover ends up where it
  does.
- **Import / export.** Paste a diagnostics download from Home
  Assistant to reproduce a real cover, and copy the current configuration back
  out as a re-importable diagnostics JSON.
- **Persistent session.** Location, cover type, configuration, entity values,
  date and time are saved in the browser, so a refresh does not lose your work.

Supported cover types in this release: **blind**, **awning** and **tilt**.

---

## How it works

```
Browser (static UI)
        │  JSON over HTTP
        ▼
FastAPI server (simulator/server.py)
        │
        ▼
simulator/harness.py  ── builds the config, reads, and pipeline snapshot
        │
        ▼
custom_components/adaptive_cover_pro/   ← the real integration
   engine/ · pipeline/ · diagnostics/ · cover_types/
```

- `server.py` exposes the HTTP API and serves the static UI.
- `schema.py` turns the integration's `FieldSpec` schema + translations into the
  form description the browser renders.
- `seed.py` normalizes an imported diagnostics payload into options and
  environment values.
- `sun.py` computes sun position and the day curve for the simulated instant.
- `harness.py` wires everything into the integration's real pipeline and
  diagnostics builder, then returns the result.

---

## Requirements

- **Python 3.12 or newer** (3.13+ recommended if you want the newest Home
  Assistant release; on Python 3.12 pip resolves Home Assistant to the 2025.1.x
  line).
- **Adaptive Cover Pro source code**, checked out next to this simulator (see
  below). The simulator imports the integration directly, so it must be
  present.
- Windows, macOS or Linux.

Python dependencies are listed in [`requirements.txt`](requirements.txt):

| Package | Purpose |
| --- | --- |
| `homeassistant` | Stable helpers used by the integration's config/entities |
| `astral` | Sun azimuth/elevation for the simulated instant |
| `pandas` | Data handling inside the engine |
| `tzdata` | IANA timezone database (required on Windows) |
| `voluptuous` | Config validation helpers |
| `fastapi`, `uvicorn[standard]` | Local web server and API |

---

## Setup

The simulator expects to live **inside** the Adaptive Cover Pro checkout, as a
sibling of `custom_components/`:

```
adaptive-cover-pro/
├── custom_components/
│   └── adaptive_cover_pro/
└── simulator/          ← this repository
    ├── server.py
    ├── harness.py
    └── ...
```

1. **Get Adaptive Cover Pro:**

   ```bash
   git clone https://github.com/jrhubott/adaptive-cover-pro.git
   cd adaptive-cover-pro
   ```

2. **Clone the simulator into that folder as `simulator`:**

   ```bash
   git clone https://github.com/jonferreira/adaptive-cover-pro-simulator.git simulator
   ```

   The folder name matters: the launchers start `simulator.server:app`, and the
   code locates `custom_components/` one level up. If you use a different name,
   the launchers adapt automatically, but keep the simulator exactly one level
   below the integration checkout.

3. **Install and run** using the launcher for your platform (below). The
   launchers create a local `.venv` and install `requirements.txt` on first run.

---

## Running the simulator

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File run.ps1
```

### macOS / Linux

```bash
chmod +x run.sh
./run.sh
```

### Manual

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# From the Adaptive Cover Pro checkout root:
python -m uvicorn simulator.server:app --host 127.0.0.1 --port 8765
```

Then open <http://127.0.0.1:8765>.

Stop the server with `Ctrl+C`.

---

## Using the UI

1. **Set your location.** Enter latitude, longitude, elevation and an IANA
   timezone (for example `Europe/Lisbon`). The defaults (0, 0, UTC) are neutral
   placeholders — set your own to get meaningful sun angles.
2. **Import a cover (optional).** In Home Assistant, open
   *Settings → Devices & services → Adaptive Cover Pro → your cover → Download
   diagnostics*, then paste the JSON into **Import diagnostics**. Both the full
   diagnostics envelope and the bare `data` payload are accepted.
3. **Configure the cover.** Choose a cover type and edit any option. Fields are
   grouped and labelled exactly as in the integration.
4. **Set entity values.** In the **Entities** panel, provide the states the
   cover would read (weather condition, temperatures, lux, climate state, …).
   The **Environment** panel holds derived/instantaneous values.
5. **Pick a moment.** Choose a date and drag the time slider; the sun diagram
   and all calculations update for that instant.
6. **Read the result.** The **Result** panel shows the computed position, the
   active pipeline branch and the diagnostics payload.
7. **Export.** Use **Copy config** to copy the current state as a re-importable
   diagnostics JSON.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: custom_components` | The simulator is not directly inside the Adaptive Cover Pro checkout. Move it so `simulator/` and `custom_components/` are siblings. |
| `Address already in use` | Another process is on port 8765. Stop it, or run `python -m uvicorn simulator.server:app --port 8766` and open that port. |
| `python` not found | Install Python 3.12+ and make sure it is on `PATH` (on Windows, the `py` launcher also works). |
| Home Assistant install fails on Python 3.12 | Newer Home Assistant releases require Python 3.13+. Either upgrade Python, or let pip install the 2025.1.x line, which is sufficient for the simulator. |
| UI looks stale after an update | Hard-refresh the page (`Ctrl/Cmd + Shift + R`). Static asset URLs are cache-busted by version query strings. |

---

## Limitations and roadmap

- v1 targets **blind**, **awning** and **tilt** cover types.
- Jinja template fields are part of the configuration but template *rendering*
  against simulated entity states is still on the roadmap.
- The simulator tracks Adaptive Cover Pro's internal APIs. If the integration
  renames or removes a module the simulator imports, the simulator may need an
  update. Pin or vendor a known-good integration version if you need
  long-term stability.
- The simulator is a development aid, not a Home Assistant add-on: it runs as a
  local Python process and never talks to your HA instance.

---

## Versioning

This project uses **CalVer** in the format `YYYY.MM.PATCH`:

- `YYYY` — year
- `MM` — month (zero-padded)
- `PATCH` — increment within the month, starting at `1`

Every change is recorded in [`CHANGELOG.md`](CHANGELOG.md) and released under a
matching git tag (`vYYYY.MM.PATCH`).
