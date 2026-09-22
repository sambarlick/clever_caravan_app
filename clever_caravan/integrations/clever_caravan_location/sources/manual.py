# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Manual source: input_number helpers for testing/fallback."""

from __future__ import annotations

import logging

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ELEVATION_ENTITY,
    CONF_LATITUDE_ENTITY,
    CONF_LONGITUDE_ENTITY,
    CONF_SPEED_ENTITY,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
)
from .base import LocationFix, LocationSource

_LOGGER = logging.getLogger(__name__)
_BAD_STATES = {None, STATE_UNAVAILABLE, STATE_UNKNOWN, ""}


def _to_float(value: str | None) -> float | None:
    if value in _BAD_STATES:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class ManualSource(LocationSource):
    """Source backed by input_number helpers."""

    async def async_start(self) -> None:
        entities = [
            self.config[CONF_LATITUDE_ENTITY],
            self.config[CONF_LONGITUDE_ENTITY],
        ]
        for opt in (CONF_ELEVATION_ENTITY, CONF_SPEED_ENTITY):
            if (eid := self.config.get(opt)) is not None:
                entities.append(eid)

        self._unsub = async_track_state_change_event(
            self.hass, entities, self._handle_change
        )
        self._emit_current()

    def _handle_change(self, _event) -> None:  # noqa: ANN001
        self._emit_current()

    def _emit_current(self) -> None:
        lat = _to_float(self._state(CONF_LATITUDE_ENTITY))
        lon = _to_float(self._state(CONF_LONGITUDE_ENTITY))
        ele = (
            _to_float(self._state(CONF_ELEVATION_ENTITY))
            if self.config.get(CONF_ELEVATION_ENTITY)
            else None
        )
        speed = (
            _to_float(self._state(CONF_SPEED_ENTITY))
            if self.config.get(CONF_SPEED_ENTITY)
            else None
        )

        if lat is None or lon is None:
            return

        valid = (
            LAT_MIN <= lat <= LAT_MAX
            and LON_MIN <= lon <= LON_MAX
            and not (lat == 0.0 and lon == 0.0)
        )

        self._publish(
            LocationFix(
                latitude=lat,
                longitude=lon,
                elevation=ele,
                speed_kmh=speed,
                timestamp=dt_util.utcnow(),
                valid=valid,
            )
        )

    def _state(self, key: str) -> str | None:
        eid = self.config.get(key)
        if not eid:
            return None
        state = self.hass.states.get(eid)
        return state.state if state else None
