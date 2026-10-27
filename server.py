"""Adaptive Cover Pro simulator — local web server."""

from __future__ import annotations

import pathlib
import sys
import traceback

# Ensure the project root is importable regardless of cwd.
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import fastapi  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import seed  # noqa: E402
from . import schema  # noqa: E402
from .harness import simulate  # noqa: E402
from .sun import day_curve  # noqa: E402

_STATIC = pathlib.Path(__file__).resolve().parent / "static"

app = fastapi.FastAPI(title="Adaptive Cover Pro Simulator")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/api/cover-types")
def api_cover_types() -> dict:
    return {"cover_types": schema.cover_types()}


@app.get("/api/schema")
def api_schema(cover_type: str) -> dict:
    return schema.cover_schema(cover_type)


@app.get("/api/sun-curve")
def api_sun_curve(
    lat: float = 0.0,
    lon: float = 0.0,
    elev: float = 0.0,
    tz: str = "UTC",
    date: str = "",
) -> dict:
    import datetime as dt

    d = dt.date.fromisoformat(date) if date else dt.date.today()
    try:
        return day_curve(lat, lon, elev, tz, d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": repr(exc)}, status_code=400)


@app.post("/api/simulate")
def api_simulate(payload: dict) -> JSONResponse:
    try:
        return JSONResponse(simulate(payload))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"error": str(exc), "traceback": traceback.format_exc()},
            status_code=400,
        )


@app.post("/api/import-diagnostics")
def api_import_diagnostics(payload: dict) -> JSONResponse:
    raw = payload.get("json")
    try:
        result = seed.from_diagnostics(raw)
        return JSONResponse(result)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)


app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
