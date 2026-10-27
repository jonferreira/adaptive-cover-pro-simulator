"""Headless simulation harness for Adaptive Cover Pro.

Drives the REAL engine + pipeline (no Home Assistant runtime) to answer
"what would this cover do right now", given a cover type, its raw config
options, a set of environment inputs, and a sun position (date + time +
coordinates).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import pathlib
from typing import Any

from custom_components.adaptive_cover_pro import const as C
from custom_components.adaptive_cover_pro.config_context_adapter import (
    ConfigContextAdapter,
)
from custom_components.adaptive_cover_pro.config_types import (
    CoverConfig,
    GlareZone,
    GlareZonesConfig,
    HorizontalConfig,
    TiltConfig,
    VerticalConfig,
)
from custom_components.adaptive_cover_pro.cover_types import get_policy
from custom_components.adaptive_cover_pro.cover_types.base import axis_inverted
from custom_components.adaptive_cover_pro.diagnostics.builder import (
    DiagnosticContext,
    DiagnosticsBuilder,
)
from custom_components.adaptive_cover_pro.engine.climate_crossings import (
    extreme_heat_crossing,
    outside_high_crossing,
    resolve_current_temperature,
    resolve_extreme_heat_active,
    summer_warm_crossing,
    winter_crossing,
)
from custom_components.adaptive_cover_pro.engine.covers import (
    AdaptiveHorizontalCover,
    AdaptiveTiltCover,
    AdaptiveVerticalCover,
)
from custom_components.adaptive_cover_pro.helpers import (
    compute_effective_default,
    custom_position_slot_configured,
    custom_position_slot_name,
    custom_position_slot_sensors,
    resolve_sunrise_offset,
    resolve_sunset_offset,
)
from custom_components.adaptive_cover_pro.pipeline.handlers import build_handlers
from custom_components.adaptive_cover_pro.pipeline.registry import PipelineRegistry
from custom_components.adaptive_cover_pro.pipeline.types import (
    ClimateOptions,
    CustomPositionSensorState,
    PipelineSnapshot,
)
from custom_components.adaptive_cover_pro.position_utils import InterpolationCurve
from custom_components.adaptive_cover_pro.state.climate_provider import ClimateReadings

from .sun import SimSunData, point_sun

_MANIFEST_VERSION = json.loads(
    (
        pathlib.Path(__file__).resolve().parent.parent
        / "custom_components"
        / "adaptive_cover_pro"
        / "manifest.json"
    ).read_text()
)["version"]

_LOGGER = logging.getLogger("acp.simulator")


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


# ---------------------------------------------------------------------------
# Typed config builders (replicating ConfigurationService, which is HA-bound)
# ---------------------------------------------------------------------------


def _vertical_config(options: dict) -> VerticalConfig:
    return VerticalConfig(
        distance=options.get(C.CONF_DISTANCE)
        if options.get(C.CONF_DISTANCE) is not None
        else C.DEFAULT_DISTANCE,
        h_win=options.get(C.CONF_HEIGHT_WIN)
        if options.get(C.CONF_HEIGHT_WIN) is not None
        else C.DEFAULT_WINDOW_HEIGHT,
        window_depth=options.get(C.CONF_WINDOW_DEPTH) or 0.0,
        sill_height=options.get(C.CONF_SILL_HEIGHT) or 0.0,
        glare_zones=_glare_zones_config(options),
    )


def _horizontal_config(options: dict) -> HorizontalConfig:
    return HorizontalConfig(
        awn_length=options.get(C.CONF_LENGTH_AWNING) or 2.0,
        awn_angle=options.get(C.CONF_AWNING_ANGLE) or 0,
        shade_mode=options.get(C.CONF_AWNING_SHADE_MODE) or C.DEFAULT_AWNING_SHADE_MODE,
    )


def _tilt_config(options: dict) -> TiltConfig:
    depth = options.get(C.CONF_TILT_DEPTH)
    distance = options.get(C.CONF_TILT_DISTANCE)
    if depth is None:
        depth = 2.5
    if distance is None:
        distance = 2.5
    return TiltConfig(
        slat_distance=float(distance) / 100,
        depth=float(depth) / 100,
        mode=options.get(C.CONF_TILT_MODE),
        angle_0=options.get(C.CONF_TILT_ANGLE_0, C.DEFAULT_TILT_ANGLE_0),
        angle_100=options.get(C.CONF_TILT_ANGLE_100, C.DEFAULT_TILT_ANGLE_100),
        horizontal_percent=options.get(
            C.CONF_TILT_HORIZONTAL_PERCENT, C.DEFAULT_TILT_HORIZONTAL_PERCENT
        ),
        max_tilt=options.get(C.CONF_MAX_TILT, C.DEFAULT_MAX_TILT),
        min_tilt=options.get(C.CONF_MIN_TILT, C.DEFAULT_MIN_TILT),
        min_tilt_sun_only=bool(
            options.get(C.CONF_MIN_TILT_SUN_ONLY, C.DEFAULT_MIN_TILT_SUN_ONLY)
        ),
        max_tilt_sun_only=bool(
            options.get(C.CONF_MAX_TILT_SUN_ONLY, C.DEFAULT_MAX_TILT_SUN_ONLY)
        ),
        safety_margin=float(
            options.get(
                C.CONF_TILT_SAFETY_MARGIN,
                options.get(C.CONF_VENETIAN_TILT_SAFETY_MARGIN, C.DEFAULT_TILT_SAFETY_MARGIN),
            )
        ),
        min_reflected_elevation=float(
            options.get(C.CONF_TILT_MIN_REFLECTED_ELEVATION, C.DEFAULT_TILT_MIN_REFLECTED_ELEVATION)
        ),
        tilt_transform=options.get(
            C.CONF_VENETIAN_TILT_TRANSFORM, C.DEFAULT_VENETIAN_TILT_TRANSFORM
        ),
    )


def _glare_zones_config(options: dict) -> GlareZonesConfig | None:
    if not options.get(C.CONF_ENABLE_GLARE_ZONES):
        return None
    zones: list[GlareZone] = []
    for i in C.GLARE_ZONE_SLOT_NUMBERS:
        name = options.get(f"glare_zone_{i}_name", "")
        if not name:
            continue
        zones.append(
            GlareZone(
                name=name,
                x=float(options.get(f"glare_zone_{i}_x", 0.0)),
                y=float(options.get(f"glare_zone_{i}_y", 1.0)),
                radius=float(options.get(f"glare_zone_{i}_radius", 0.3)),
                z=float(options.get(f"glare_zone_{i}_z", C.DEFAULT_GLARE_ZONE_Z)),
            )
        )
    if not zones:
        return None
    return GlareZonesConfig(
        zones=zones, window_width=float(options.get(C.CONF_WINDOW_WIDTH, 1.0))
    )


def _build_cover(
    cover_type: str,
    *,
    sol_azi: float,
    sol_elev: float,
    sun_data: SimSunData,
    config: CoverConfig,
    options: dict,
    logger: ConfigContextAdapter,
):
    if cover_type == C.CoverType.BLIND:
        return AdaptiveVerticalCover(
            logger=logger,
            sol_azi=sol_azi,
            sol_elev=sol_elev,
            sun_data=sun_data,
            config=config,
            vert_config=_vertical_config(options),
        )
    if cover_type == C.CoverType.AWNING:
        return AdaptiveHorizontalCover(
            logger=logger,
            sol_azi=sol_azi,
            sol_elev=sol_elev,
            sun_data=sun_data,
            config=config,
            vert_config=_vertical_config(options),
            horiz_config=_horizontal_config(options),
        )
    if cover_type == C.CoverType.TILT:
        return AdaptiveTiltCover(
            logger=logger,
            sol_azi=sol_azi,
            sol_elev=sol_elev,
            sun_data=sun_data,
            config=config,
            tilt_config=_tilt_config(options),
        )
    raise ValueError(f"Unsupported cover type for simulator: {cover_type!r}")


# ---------------------------------------------------------------------------
# Environment → derived manager state
# ---------------------------------------------------------------------------


def _weather_active(options: dict, env: dict) -> bool:
    if not options.get(C.CONF_WEATHER_ENABLED, C.DEFAULT_WEATHER_ENABLED):
        return False
    wind_sensor = options.get(C.CONF_WEATHER_WIND_SPEED_SENSOR)
    wind_dir_sensor = options.get(C.CONF_WEATHER_WIND_DIRECTION_SENSOR)
    wind_threshold = _num(
        options.get(C.CONF_WEATHER_WIND_SPEED_THRESHOLD, C.DEFAULT_WEATHER_WIND_SPEED_THRESHOLD)
    )
    wind_dir_tol = _num(
        options.get(C.CONF_WEATHER_WIND_DIRECTION_TOLERANCE, C.DEFAULT_WEATHER_WIND_DIRECTION_TOLERANCE)
    )
    win_azi = options.get(C.CONF_AZIMUTH, C.DEFAULT_WINDOW_AZIMUTH)

    wind_active = False
    if wind_sensor:
        speed = _num(env.get("wind_speed"))
        if speed is not None and wind_threshold is not None and speed >= wind_threshold:
            direction = _num(env.get("wind_direction"))
            if wind_dir_sensor and direction is not None and wind_dir_tol is not None:
                diff = abs(direction - (win_azi or 0)) % C.DEGREES_IN_CIRCLE
                angular = min(diff, C.DEGREES_IN_CIRCLE - diff)
                wind_active = angular <= wind_dir_tol
            else:
                wind_active = True

    rain_active = False
    rain_sensor = options.get(C.CONF_WEATHER_RAIN_SENSOR)
    rain_threshold = _num(options.get(C.CONF_WEATHER_RAIN_THRESHOLD, C.DEFAULT_WEATHER_RAIN_THRESHOLD))
    if rain_sensor and rain_threshold is not None:
        rate = _num(env.get("rain_rate"))
        rain_active = rate is not None and rate >= rain_threshold

    raining = bool(env.get("is_raining")) and bool(options.get(C.CONF_WEATHER_IS_RAINING_SENSOR))
    windy = bool(env.get("is_windy")) and bool(options.get(C.CONF_WEATHER_IS_WINDY_SENSOR))
    severe = bool(env.get("severe_active")) and bool(options.get(C.CONF_WEATHER_SEVERE_SENSORS) or [])

    return bool(wind_active or rain_active or raining or windy or severe)


def _build_climate_readings(options: dict, env: dict) -> ClimateReadings:
    outside = _num(env.get("outside_temperature"))
    inside = _num(env.get("inside_temperature"))
    temp_switch = _coerce_bool(env.get("temp_switch"))
    lux = _num(env.get("lux"))
    irradiance = _num(env.get("irradiance"))
    cloud = _num(env.get("cloud_coverage"))

    lux_entity = options.get(C.CONF_LUX_ENTITY)
    irr_entity = options.get(C.CONF_IRRADIANCE_ENTITY)
    cloud_entity = options.get(C.CONF_CLOUD_COVERAGE_ENTITY)
    lux_threshold = _num(options.get(C.CONF_LUX_THRESHOLD))
    irr_threshold = _num(options.get(C.CONF_IRRADIANCE_THRESHOLD))
    cloud_threshold = _num(options.get(C.CONF_CLOUD_COVERAGE_THRESHOLD))

    lux_below = bool(lux_entity and lux is not None and lux_threshold is not None and lux <= lux_threshold)
    irr_below = bool(
        irr_entity and irradiance is not None and irr_threshold is not None and irradiance <= irr_threshold
    )
    cloud_above = bool(
        cloud_entity and cloud is not None and cloud_threshold is not None and cloud >= cloud_threshold
    )

    current = resolve_current_temperature(outside, inside, temp_switch=temp_switch)
    below_low, low_cleared = winter_crossing(
        current,
        _num(options.get(C.CONF_TEMP_LOW)),
        _num(options.get(C.CONF_TEMP_LOW_RELEASE_THRESHOLD)),
    )
    above_high, high_cleared = summer_warm_crossing(
        current,
        _num(options.get(C.CONF_TEMP_HIGH)),
        _num(options.get(C.CONF_TEMP_HIGH_RELEASE_THRESHOLD)),
    )
    outside_high, outside_cleared = outside_high_crossing(
        outside,
        _num(options.get(C.CONF_OUTSIDE_THRESHOLD)),
        _num(options.get(C.CONF_OUTSIDE_THRESHOLD_RELEASE)),
    )
    extreme, extreme_cleared = extreme_heat_crossing(
        outside,
        _num(options.get(C.CONF_TEMP_EXTREME_HEAT)),
        _num(options.get(C.CONF_TEMP_EXTREME_HEAT_RELEASE_THRESHOLD)),
    )

    return ClimateReadings(
        outside_temperature=outside,
        inside_temperature=inside,
        is_presence=_coerce_bool(env.get("is_presence"), True),
        is_sunny=_coerce_bool(env.get("is_sunny"), True),
        lux_below_threshold=lux_below,
        irradiance_below_threshold=irr_below,
        cloud_coverage_above_threshold=cloud_above,
        irradiance_value=irradiance,
        temp_below_low_threshold=below_low,
        temp_low_release_cleared=low_cleared,
        temp_above_high_threshold=above_high,
        temp_high_release_cleared=high_cleared,
        outside_above_threshold=outside_high,
        outside_release_cleared=outside_cleared,
        outside_above_extreme_heat=extreme,
        extreme_heat_release_cleared=extreme_cleared,
        inside_temperature_source="sim",
        outside_temperature_source="sim",
    )


def _custom_positions(options: dict, env: dict) -> list[CustomPositionSensorState]:
    result: list[CustomPositionSensorState] = []
    active = env.get("custom_position_active", {}) or {}
    for slot, slot_keys in C.CUSTOM_POSITION_SLOTS.items():
        enabled = bool(options.get(slot_keys["enabled"], C.DEFAULT_CUSTOM_POSITION_ENABLED))
        if not (custom_position_slot_configured(options, slot_keys) and enabled):
            continue
        sensors = custom_position_slot_sensors(options, slot_keys)
        is_on = _coerce_bool(active.get(str(slot)))
        raw_tilt = options.get(slot_keys["tilt"])
        raw_pos = options.get(slot_keys["position"])
        pos_max = options.get(slot_keys["position_max"])
        t_min = options.get(slot_keys["tilt_min"])
        t_max = options.get(slot_keys["tilt_max"])
        result.append(
            CustomPositionSensorState(
                entity_ids=tuple(sensors),
                is_on=is_on,
                position=int(raw_pos) if raw_pos is not None else None,
                priority=int(options.get(slot_keys["priority"]) or C.DEFAULT_CUSTOM_POSITION_PRIORITY),
                min_mode=bool(options.get(slot_keys["min_mode"], False)),
                use_my=bool(options.get(slot_keys["use_my"], False)),
                tilt=int(raw_tilt) if raw_tilt is not None else None,
                tilt_only=bool(options.get(slot_keys["tilt_only"], C.DEFAULT_CUSTOM_POSITION_TILT_ONLY)),
                slot=slot,
                active_entity_ids=tuple(sensors) if is_on else (),
                custom_name=custom_position_slot_name(options, slot_keys),
                position_max=int(pos_max) if pos_max is not None else None,
                tilt_min=int(t_min) if t_min is not None else None,
                tilt_max=int(t_max) if t_max is not None else None,
                outside_window=bool(options.get(slot_keys["outside_window"], False)),
                scope_to_window=bool(options.get(slot_keys["scope_to_window"], False)),
                is_valid=True,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _trace_to_dicts(result) -> list[dict]:
    out = []
    for step in getattr(result, "decision_trace", []) or []:
        out.append(
            {
                "handler": step.handler,
                "matched": step.matched,
                "reason": step.reason,
                "position": step.position,
                "tilt": step.tilt,
                "priority": step.priority,
                "held_position": step.held_position,
            }
        )
    return out


def simulate(payload: dict) -> dict:
    cover_type = payload.get("cover_type", C.CoverType.BLIND)
    options = payload.get("options") or {}
    env = payload.get("environment") or {}
    loc = payload.get("location") or {}

    lat = float(loc.get("lat", 0.0))
    lon = float(loc.get("lon", 0.0))
    elevation = float(loc.get("elevation", loc.get("elev", 0.0)))
    timezone = loc.get("timezone") or loc.get("tz") or "UTC"
    date = dt.date.fromisoformat(payload.get("date") or dt.date.today().isoformat())
    minutes = int(payload.get("time_minutes", 720))

    # Sun position at the chosen instant.
    psun = point_sun(lat, lon, elevation, timezone, date, minutes)
    sol_azi = psun["azimuth"]
    sol_elev = psun["elevation"]
    eval_time = psun["utc"]

    sun_data = SimSunData(timezone, lat, lon, elevation, date)
    logger = ConfigContextAdapter(_LOGGER)
    policy = get_policy(cover_type)

    config = CoverConfig.from_options(options)
    cover = _build_cover(
        cover_type,
        sol_azi=sol_azi,
        sol_elev=sol_elev,
        sun_data=sun_data,
        config=config,
        options=options,
        logger=logger,
    )
    cover.eval_time = eval_time

    # Effective default + sunset flag.
    default_position, is_sunset_active = compute_effective_default(
        int(options.get(C.CONF_DEFAULT_HEIGHT, 0)),
        options.get(C.CONF_SUNSET_POS),
        sun_data,
        resolve_sunset_offset(options),
        resolve_sunrise_offset(options),
        eval_time=eval_time,
    )

    climate_mode_enabled = _coerce_bool(env.get("climate_mode_enabled"), bool(options.get(C.CONF_CLIMATE_MODE)))
    climate_readings = _build_climate_readings(options, env)

    cloud_suppression_active = env.get("cloud_suppression_active")
    if cloud_suppression_active is None:
        cloud_suppression_active = bool(options.get(C.CONF_CLOUD_SUPPRESSION)) and (
            not climate_readings.is_sunny
            or climate_readings.lux_below_threshold
            or climate_readings.irradiance_below_threshold
            or climate_readings.cloud_coverage_above_threshold
        )
    else:
        cloud_suppression_active = bool(cloud_suppression_active) and bool(
            options.get(C.CONF_CLOUD_SUPPRESSION)
        )

    climate_extreme_heat_active = climate_mode_enabled and bool(
        resolve_extreme_heat_active(
            climate_readings.outside_temperature,
            _num(options.get(C.CONF_TEMP_EXTREME_HEAT)),
            None,
        )
    )

    weather_active = _weather_active(options, env)
    weather_override_tilt = (
        options.get(C.CONF_WEATHER_OVERRIDE_TILT) if policy.weather_override_includes_tilt else None
    )
    cloudy_tilt = options.get(C.CONF_CLOUDY_TILT) if policy.cloud_suppression_includes_tilt else None

    climate_options = ClimateOptions(
        temp_low=_num(options.get(C.CONF_TEMP_LOW)),
        temp_high=_num(options.get(C.CONF_TEMP_HIGH)),
        temp_switch=_coerce_bool(env.get("temp_switch")),
        transparent_blind=options.get(C.CONF_TRANSPARENT_BLIND, False),
        temp_summer_outside=_num(options.get(C.CONF_OUTSIDE_THRESHOLD)),
        cloud_suppression_enabled=bool(options.get(C.CONF_CLOUD_SUPPRESSION, False)),
        winter_close_insulation=bool(options.get(C.CONF_WINTER_CLOSE_INSULATION, False)),
        summer_close_bypass_sun_floor=bool(options.get(C.CONF_SUMMER_CLOSE_BYPASS_SUN_FLOOR, False)),
        cloudy_position=options.get(C.CONF_CLOUDY_POSITION),
        cloudy_tilt=cloudy_tilt,
        temp_extreme_heat=_num(options.get(C.CONF_TEMP_EXTREME_HEAT)),
        extreme_heat_position=options.get(C.CONF_EXTREME_HEAT_POSITION),
        tracking_seasons=(
            frozenset(C.DEFAULT_TRACKING_SEASONS)
            if options.get(C.CONF_TRACKING_SEASONS) is None
            else frozenset(options[C.CONF_TRACKING_SEASONS])
        ),
    )

    enable_sun_tracking = env.get("enable_sun_tracking")
    if enable_sun_tracking is None:
        enable_sun_tracking = bool(options.get(C.CONF_ENABLE_SUN_TRACKING, True))

    interp_enabled = bool(options.get(C.CONF_INTERP))
    interp_curve = (
        InterpolationCurve(
            start_value=options.get(C.CONF_INTERP_START),
            end_value=options.get(C.CONF_INTERP_END),
            normal_list=options.get(C.CONF_INTERP_LIST),
            new_list=options.get(C.CONF_INTERP_LIST_NEW),
        )
        if interp_enabled
        else None
    )

    cur_pos = _num(env.get("current_cover_position"))
    cur_pos_int = int(round(cur_pos)) if cur_pos is not None else None

    glare = _glare_zones_config(options)
    active_zone_names = frozenset(z.name for z in glare.zones) if glare is not None else frozenset()

    snapshot = PipelineSnapshot(
        cover=cover,
        config=config,
        cover_type=cover_type,
        policy=policy,
        default_position=default_position,
        is_sunset_active=is_sunset_active,
        climate_readings=climate_readings,
        climate_mode_enabled=climate_mode_enabled,
        climate_options=climate_options,
        climate_extreme_heat_active=climate_extreme_heat_active,
        manual_override_active=_coerce_bool(env.get("manual_override_active")),
        motion_timeout_active=_coerce_bool(env.get("motion_timeout_active")),
        weather_override_active=weather_active,
        weather_override_position=options.get(C.CONF_WEATHER_OVERRIDE_POSITION, 0) or 0,
        weather_override_tilt=weather_override_tilt,
        weather_override_min_mode=bool(options.get(C.CONF_WEATHER_OVERRIDE_MIN_MODE, False)),
        weather_outside_window=bool(
            options.get(C.CONF_WEATHER_OUTSIDE_WINDOW, C.DEFAULT_WEATHER_OUTSIDE_WINDOW)
        ),
        weather_bypass_auto_control=bool(options.get(C.CONF_WEATHER_BYPASS_AUTO_CONTROL, True)),
        glare_zones=glare,
        active_zone_names=active_zone_names,
        in_time_window=_coerce_bool(env.get("in_time_window"), True),
        clock_window_open=_coerce_bool(env.get("clock_window_open"), True),
        motion_control_enabled=_coerce_bool(env.get("motion_control_enabled"), True),
        custom_position_sensors=_custom_positions(options, env),
        my_position_value=options.get(C.CONF_MY_POSITION_VALUE),
        sunset_use_my=bool(options.get(C.CONF_SUNSET_USE_MY, False)),
        enable_sun_tracking=enable_sun_tracking,
        motion_timeout_mode=options.get(C.CONF_MOTION_TIMEOUT_MODE, C.DEFAULT_MOTION_TIMEOUT_MODE),
        current_cover_position=cur_pos_int,
        cover_positions={e: cur_pos_int for e in options.get(C.CONF_ENTITIES, [])} if cur_pos_int is not None else None,
        position_axis_inverted=axis_inverted(policy.axes[0], options),
        interp_curve=interp_curve,
        minimize_movements=bool(options.get(C.CONF_MINIMIZE_MOVEMENTS, C.DEFAULT_MINIMIZE_MOVEMENTS)),
        max_coverage_steps=int(options.get(C.CONF_MAX_COVERAGE_STEPS, C.DEFAULT_MAX_COVERAGE_STEPS)),
        snap_closed_below=bool(options.get(C.CONF_SNAP_CLOSED_BELOW, C.DEFAULT_SNAP_CLOSED_BELOW)),
        snap_closed_threshold=int(options.get(C.CONF_SNAP_CLOSED_THRESHOLD, C.DEFAULT_SNAP_CLOSED_THRESHOLD)),
        default_tilt=options.get(C.CONF_DEFAULT_TILT),
        sunset_tilt=options.get(C.CONF_SUNSET_TILT),
        min_tilt=int(options.get(C.CONF_MIN_TILT, C.DEFAULT_MIN_TILT)),
        max_tilt=int(options.get(C.CONF_MAX_TILT, C.DEFAULT_MAX_TILT)),
        min_tilt_sun_only=bool(options.get(C.CONF_MIN_TILT_SUN_ONLY, C.DEFAULT_MIN_TILT_SUN_ONLY)),
        max_tilt_sun_only=bool(options.get(C.CONF_MAX_TILT_SUN_ONLY, C.DEFAULT_MAX_TILT_SUN_ONLY)),
        solar_floor_active=not _coerce_bool(env.get("set_position"), True),
        time_threshold_minutes=0,  # anticipation disabled in v1
        cloud_suppression_active=cloud_suppression_active,
        cloud_escalation_active=_coerce_bool(env.get("cloud_escalation_active")),
        unshaded_position=policy.position_for_intent(sun_through=True),
    )

    registry = PipelineRegistry(build_handlers(options))
    result = registry.evaluate(snapshot)

    # Coordinator post-processing: annotate raw config values + effective default.
    result = dataclasses.replace(
        result,
        default_position=default_position,
        is_sunset_active=is_sunset_active,
        configured_default=int(options.get(C.CONF_DEFAULT_HEIGHT, 0)),
        configured_sunset_pos=options.get(C.CONF_SUNSET_POS),
        configured_cloudy_pos=options.get(C.CONF_CLOUDY_POSITION),
    )

    # Rebuild the same diagnostics payload a real "download diagnostics" emits.
    ctx = DiagnosticContext(
        pos_sun=[sol_azi, sol_elev],
        cover=cover,
        pipeline_result=result,
        climate_mode=climate_mode_enabled,
        check_adaptive_time=_coerce_bool(env.get("in_time_window"), True),
        after_start_time=True,
        before_end_time=True,
        start_time=options.get(C.CONF_START_TIME),
        end_time=options.get(C.CONF_END_TIME),
        automatic_control=True,
        config_options=options,
        resolved_options=options,
        covers={},
        cover_type=cover_type,
        integration_version=_MANIFEST_VERSION,
        last_update_success=True,
    )
    try:
        diagnostics, explanation = DiagnosticsBuilder().build(ctx)
    except Exception as exc:  # noqa: BLE001 — diagnostics must never break the preview
        diagnostics = {"error": repr(exc)}
        explanation = ""

    control_method_label = getattr(result.control_method, "value", str(result.control_method))

    return {
        "sun": {
            "azimuth": round(sol_azi, 1),
            "elevation": round(sol_elev, 1),
            "utc": eval_time.isoformat(),
            "local": psun["local"].isoformat(),
        },
        "cover": {
            "type": cover_type,
            "gamma": round(float(cover.gamma), 1) if getattr(cover, "gamma", None) is not None else None,
            "valid": bool(cover.valid),
            "direct_sun_valid": bool(cover.direct_sun_valid),
            "in_fov": bool(cover.in_fov),
            "sun_behind_plane": bool(getattr(cover, "sun_behind_plane", False)),
            "control_state_reason": getattr(cover, "control_state_reason", None),
        },
        "result": {
            "position": result.position,
            "tilt": result.tilt,
            "control_method": control_method_label,
            "reason": result.reason,
            "raw_calculated_position": result.raw_calculated_position,
            "held_position": result.held_position,
            "is_safety": result.is_safety,
            "bypass_auto_control": result.bypass_auto_control,
            "skip_command": result.skip_command,
            "use_my_position": result.use_my_position,
            "default_position": result.default_position,
            "is_sunset_active": result.is_sunset_active,
            "climate_strategy": getattr(result.climate_strategy, "value", result.climate_strategy),
            "decision_trace": _trace_to_dicts(result),
        },
        "default_position": default_position,
        "is_sunset_active": is_sunset_active,
        "weather_override_active": weather_active,
        "cloud_suppression_active": cloud_suppression_active,
        "climate_extreme_heat_active": climate_extreme_heat_active,
        "diagnostics": diagnostics,
        "position_explanation": explanation,
    }
