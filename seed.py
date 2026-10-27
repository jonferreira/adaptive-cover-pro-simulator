"""Parse a Home Assistant "Download diagnostics" JSON into simulator inputs."""

from __future__ import annotations

from typing import Any


def from_diagnostics(raw: str | dict) -> dict:
    """Extract cover type, options, and seedable environment values.

    Accepts the exact envelope Home Assistant's "Download diagnostics" button
    produces (``config_data`` + ``config_options`` + ``diagnostics``), or a
    bare diagnostics payload.
    """
    data: dict = raw if isinstance(raw, dict) else _load(raw)

    # Home Assistant core wraps the integration's diagnostics under a top-level
    # "data" key (see homeassistant.components.diagnostics._async_get_json_file_response).
    # Accept both the full HA envelope and the bare integration payload.
    if isinstance(data.get("data"), dict):
        data = data["data"]

    cover_type = None
    options: dict = {}
    config_data = data.get("config_data") or {}
    options = dict(data.get("config_options") or {})

    cover_type = config_data.get("sensor_type") or config_data.get("cover_type")

    diag = data.get("diagnostics") or data

    env: dict[str, Any] = {}

    # Temperature details (issue #786).
    temp_details = diag.get("temperature_details")
    if isinstance(temp_details, dict):
        if temp_details.get("inside_temperature") is not None:
            env["inside_temperature"] = temp_details.get("inside_temperature")
        if temp_details.get("outside_temperature") is not None:
            env["outside_temperature"] = temp_details.get("outside_temperature")

    # Climate conditions booleans.
    conditions = diag.get("climate_conditions")
    if isinstance(conditions, dict):
        if conditions.get("is_sunny") is not None:
            env["is_sunny"] = bool(conditions.get("is_sunny"))
        if conditions.get("is_presence") is not None:
            env["is_presence"] = bool(conditions.get("is_presence"))
        if conditions.get("cloud_coverage_above_threshold") is not None:
            env["cloud_coverage_above"] = bool(conditions.get("cloud_coverage_above_threshold"))

    # Raw irradiance from the solar-gain estimate (issue #1237).
    gain = diag.get("solar_gain")
    if isinstance(gain, dict) and gain.get("ghi_w_m2") is not None:
        env["irradiance"] = gain.get("ghi_w_m2")

    # Live sun angles (informational — the sim recomputes from coordinates).
    sun_azimuth = diag.get("sun_azimuth")
    sun_elevation = diag.get("sun_elevation")

    return {
        "cover_type": cover_type,
        "options": options,
        "environment": env,
        "meta": {
            "sun_azimuth": sun_azimuth,
            "sun_elevation": sun_elevation,
            "cover_type": diag.get("meta", {}).get("cover_type") if isinstance(diag.get("meta"), dict) else None,
        },
    }


def _load(raw: str) -> dict:
    import json

    return json.loads(raw)
