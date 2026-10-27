"""Serialize a cover type's config schema into JSON for the frontend form.

Field labels, descriptions, section titles, and section icons are read from the
integration's own ``translations/en.json`` so the form mirrors the HA options
flow exactly (menu icons live embedded in the ``options.step.init.menu_options``
strings, e.g. "☀️ Sun Tracking").
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector as sel

from custom_components.adaptive_cover_pro.cover_types import get_policy

# Cover types the harness can actually drive today (Phase 1).
SUPPORTED_COVER_TYPES = ("cover_blind", "cover_awning", "cover_tilt")

_TRANSLATIONS: dict | None = None


def _translations() -> dict:
    global _TRANSLATIONS
    if _TRANSLATIONS is None:
        p = (
            pathlib.Path(__file__).resolve().parent.parent
            / "custom_components"
            / "adaptive_cover_pro"
            / "translations"
            / "en.json"
        )
        _TRANSLATIONS = json.loads(p.read_text(encoding="utf-8"))
    return _TRANSLATIONS


def _options_step(section: str) -> dict:
    return _translations().get("options", {}).get("step", {}).get(section, {}) or {}


def _humanize(key: str) -> str:
    s = key.replace("_", " ").strip()
    s = re.sub(r"^(set|enable|disable|conf|use)_", "", s)
    return s[0].upper() + s[1:] if s else s


def _section_title(section: str) -> str:
    menu = (
        _translations()
        .get("options", {})
        .get("step", {})
        .get("init", {})
        .get("menu_options", {})
        .get(section)
    )
    if menu:
        return menu
    return _options_step(section).get("title") or _humanize(section)


def _section_description(section: str) -> str:
    return _options_step(section).get("description") or ""


def _slot_key(section: str, key: str) -> str | None:
    """Return the generic slot-subkey a slotted field maps to, or None."""
    if section == "custom_position":
        for g in (_options_step("custom_position_slot").get("data") or {}):
            if key == g or re.fullmatch(re.escape(g) + r"_\d+", key):
                return g
    elif section == "blind_spot":
        for g in (_options_step("blind_spot_slot").get("data") or {}):
            if key == g or re.fullmatch(re.escape(g) + r"_\d+", key):
                return g
    elif section == "glare_zones":
        m = re.match(r"^glare_zone_(\d+)_(\w+)$", key)
        if m:
            return "glare_zone_" + m.group(2)
    return None


def _slot_number(section: str, key: str) -> str | None:
    if section in ("custom_position", "blind_spot"):
        m = re.search(r"_(\d+)$", key)
        return m.group(1) if m else None
    if section == "glare_zones":
        m = re.match(r"^glare_zone_(\d+)_", key)
        return m.group(1) if m else None
    return None


def _field_label(section: str, key: str) -> str:
    data = _options_step(section).get("data") or {}
    if key in data:
        return data[key]
    generic = _slot_key(section, key)
    if generic:
        labels = _options_step(_slot_step(section)).get("data") or {}
        if generic in labels:
            return labels[generic]
    return _humanize(key)


def _slot_step(section: str) -> str:
    return {
        "custom_position": "custom_position_slot",
        "blind_spot": "blind_spot_slot",
        "glare_zones": "glare_zone_slot",
    }.get(section, section)


def _field_description(section: str, key: str) -> str:
    descs = _options_step(section).get("data_description") or {}
    if key in descs:
        return descs[key]
    generic = _slot_key(section, key)
    if generic:
        descs = _options_step(_slot_step(section)).get("data_description") or {}
        if generic in descs:
            return descs[generic]
    return ""


def _cfg_get(cfg: Any, key: str, default: Any = None) -> Any:
    """Read one key from a selector config that may be a dict or an object."""
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def _selector_option_labels(translation_key: str | None) -> dict[str, str]:
    if not translation_key:
        return {}
    block = _translations().get("selector", {}).get(translation_key, {})
    return block.get("options", {}) or {}


def _mode_value(mode: Any) -> Any:
    return getattr(mode, "value", mode)


def _selector_info(s: Any) -> dict:
    if isinstance(s, sel.BooleanSelector):
        return {"control": "boolean"}
    if isinstance(s, sel.NumberSelector):
        cfg = s.config
        info: dict[str, Any] = {"control": "number"}
        info["min"] = _cfg_get(cfg, "min")
        info["max"] = _cfg_get(cfg, "max")
        info["step"] = _cfg_get(cfg, "step")
        info["unit"] = _cfg_get(cfg, "unit_of_measurement")
        mode = _cfg_get(cfg, "mode")
        info["mode"] = _mode_value(mode) if mode is not None else None
        return info
    if isinstance(s, sel.SelectSelector):
        cfg = s.config
        opts = list(_cfg_get(cfg, "options") or [])
        multiple = bool(_cfg_get(cfg, "multiple", False))
        custom_value = bool(_cfg_get(cfg, "custom_value", False))
        labels = _selector_option_labels(_cfg_get(cfg, "translation_key"))
        info: dict[str, Any] = {
            "control": "select",
            "multiple": multiple,
            "custom_value": custom_value,
            "options": [{"value": v, "label": labels.get(v, v)} for v in opts],
        }
        mode = _cfg_get(cfg, "mode")
        info["mode"] = _mode_value(mode) if mode is not None else None
        return info
    if isinstance(s, sel.EntitySelector):
        return {"control": "entity"}
    if isinstance(s, sel.TemplateSelector):
        return {"control": "template"}
    if isinstance(s, sel.TextSelector):
        return {"control": "text"}
    if isinstance(s, sel.TimeSelector):
        return {"control": "time"}
    if isinstance(s, sel.DurationSelector):
        return {"control": "duration"}
    if isinstance(s, sel.IconSelector):
        return {"control": "text"}
    return {"control": "text", "_type": type(s).__name__}


def _default(marker: vol.Marker) -> Any:
    d = getattr(marker, "default", vol.UNDEFINED)
    if d is vol.UNDEFINED:
        return None
    # HA's config flow wraps defaults in a `default_factory` lambda.
    if callable(d):
        try:
            d = d()
        except Exception:  # noqa: BLE001
            return None
    if hasattr(d, "value") and not isinstance(d, (str, int, float, bool)):
        d = d.value
    if isinstance(d, (set, frozenset, tuple)):
        d = list(d)
    try:
        json.dumps(d)
        return d
    except (TypeError, ValueError):
        return None


def cover_schema(cover_type: str) -> dict:
    policy = get_policy(cover_type)
    sections = []
    for section in policy.section_order():
        try:
            schema = policy.build_section_schema(section, None, {})
        except Exception:  # noqa: BLE001 — a dynamic section must not break the whole form
            continue
        fields = []
        for marker, selector in schema.schema.items():
            key = str(marker)
            info = _selector_info(selector)
            info["key"] = key
            info["label"] = _field_label(section, key)
            info["description"] = _field_description(section, key)
            slot = _slot_number(section, key)
            if slot:
                info["label"] = f"{info['label']} ({slot})"
            info["default"] = _default(marker)
            info["required"] = isinstance(marker, vol.Required)
            fields.append(info)
        if fields:
            sections.append(
                {
                    "name": section,
                    "title": _section_title(section),
                    "description": _section_description(section),
                    "fields": fields,
                }
            )
    return {"cover_type": cover_type, "sections": sections}


def cover_types() -> list[dict]:
    out = []
    for key in SUPPORTED_COVER_TYPES:
        policy = get_policy(key)
        out.append({"id": str(key), "label": policy.display_label()})
    return out
