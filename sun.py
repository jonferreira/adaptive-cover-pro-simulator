"""Sun position helpers for the ACP simulator.

Reimplements just enough of ``custom_components.adaptive_cover_pro.sun.SunData``
to work for an *arbitrary* date (the production class is hard-wired to
``date.today()``). Uses the exact same ``astral`` calls so the numbers match
production byte-for-byte.
"""

from __future__ import annotations

import datetime as dt
from datetime import timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from astral import LocationInfo
from astral.location import Location

UTC = dt.timezone.utc


def make_location(lat: float, lon: float, timezone: str, elevation: float) -> Location:
    """Build an astral Location from coordinates."""
    return Location(LocationInfo("", "", timezone, float(lat), float(lon)))


def point_sun(
    lat: float,
    lon: float,
    elevation: float,
    timezone: str,
    date: dt.date,
    minutes: int,
) -> dict:
    """Return az/el + the UTC instant for a local date + minutes-since-midnight."""
    local_naive = dt.datetime.combine(date, dt.time(hour=0, minute=0)) + timedelta(
        minutes=int(minutes)
    )
    try:
        tz = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001 — fall back to UTC
        tz = UTC
    local_aware = local_naive.replace(tzinfo=tz)
    utc = local_aware.astimezone(UTC)
    location = make_location(lat, lon, timezone, elevation)
    azi = float(location.solar_azimuth(utc, elevation))
    elev = float(location.solar_elevation(utc, elevation))
    return {"azimuth": azi, "elevation": elev, "utc": utc, "local": local_aware}


class SimSunData:
    """Minimal ``SunData`` stand-in parameterized by an explicit date."""

    def __init__(
        self, timezone: str, lat: float, lon: float, elevation: float, date: dt.date
    ) -> None:
        self.timezone = timezone
        self.elevation = float(elevation)
        self.date = date
        self.location = make_location(lat, lon, timezone, elevation)

        end_date = date + timedelta(days=1)
        self._times = pd.date_range(
            start=date, end=end_date, freq="5min", tz=timezone, name="time"
        )
        self._azi = [self.location.solar_azimuth(t, self.elevation) for t in self._times]
        self._ele = [self.location.solar_elevation(t, self.elevation) for t in self._times]

    @property
    def times(self) -> pd.DatetimeIndex:
        return self._times

    @property
    def solar_azimuth(self) -> list[float]:
        return self._azi

    @property
    def solar_elevation(self) -> list[float]:
        return self._ele

    def sunset(self) -> dt.datetime:
        return self.location.sunset(self.date, local=False)

    def sunrise(self) -> dt.datetime:
        return self.location.sunrise(self.date, local=False)

    def next_sunset(self) -> dt.datetime:
        return self.location.sunset(self.date + timedelta(days=1), local=False)

    def next_sunrise(self) -> dt.datetime:
        return self.location.sunrise(self.date + timedelta(days=1), local=False)


def day_curve(
    lat: float,
    lon: float,
    elevation: float,
    timezone: str,
    date: dt.date,
) -> dict:
    """Full-day 5-minute azimuth/elevation curve plus sunrise/sunset."""
    location = make_location(lat, lon, timezone, elevation)
    try:
        tz = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001
        tz = UTC
    end = date + timedelta(days=1)
    times = pd.date_range(start=date, end=end, freq="5min", tz=tz, name="time")
    azi = [float(location.solar_azimuth(t, elevation)) for t in times]
    ele = [float(location.solar_elevation(t, elevation)) for t in times]

    # sunrise/sunset in the location's local time (for the slider scale).
    sunrise_utc = location.sunrise(date, local=False)
    sunset_utc = location.sunset(date, local=False)

    def _local(aware: dt.datetime) -> str:
        return aware.astimezone(tz).strftime("%H:%M")

    return {
        "times": [t.strftime("%H:%M") for t in times],
        "azimuth": azi,
        "elevation": ele,
        "sunrise": _local(sunrise_utc),
        "sunset": _local(sunset_utc),
        "timezone": timezone,
    }
