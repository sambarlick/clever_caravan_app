# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Entity-based location source.

Reads lat/lon (and optional elevation/speed) from configured HA entities.
Handles Starlink (entity-based), Companion app device_tracker, MQTT
GPS (via existing MQTT-discovered entities), and anything else that
surfaces lat/lon as entities. The single most general source adapter.

For device_tracker entities the coordinates live in state attributes
(latitude / longitude / altitude), not the entity state, so those are
read from attributes automatically — point both the latitude and
longitude fields at the same device_tracker.
"""

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

# Which device_tracker attribute backs each coordinate field.
#
# device_tracker entities (Companion app, MQTT GPS trackers, etc.) carry
# their position in attributes, not in the entity state — the state is a
# zone name like "home"/"not_home". When a configured entity is a
# device_tracker, the value is read from the mapped attribute instead of
# the state.
#
# CONF_SPEED_ENTITY is deliberately absent: device_tracker "speed"
# attributes are not consistently km/h (the Companion app reports m/s),
# and feeding that straight into the km/h driving classifier would
# misclassify. A device_tracker pointed at the speed field yields no
# speed (its state isn't numeric); point speed at a known-unit sensor.
_DEVICE_TRACKER_ATTR: dict[str, str] = {
    CONF_LATITUDE_ENTITY: "latitude",
    CONF_LONGITUDE_ENTITY: "longitude",
    CONF_ELEVATION_ENTITY: "altitude",
}


def _to_float(value: str | float | None) -> float | None:
    if value in _BAD_STATES:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class EntitySource(LocationSource):
    """Source that reads from configured HA entities."""

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
        # Emit current state once so we don't wait for the next push.
        self._emit_current()

    def _handle_change(self, _event) -> None:  # noqa: ANN001
        self._emit_current()

    def _emit_current(self) -> None:
        lat = self._value(CONF_LATITUDE_ENTITY)
        lon = self._value(CONF_LONGITUDE_ENTITY)
        ele = self._value(CONF_ELEVATION_ENTITY)
        speed = self._value(CONF_SPEED_ENTITY)

        if lat is None or lon is None:
            return  # not yet available

        valid = (
            LAT_MIN <= lat <= LAT_MAX
            and LON_MIN <= lon <= LON_MAX
            and not (lat == 0.0 and lon == 0.0)  # Null Island
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

    def _value(self, key: str) -> float | None:
        """Resolve a configured entity to a float.

        Reads the entity state normally, except for device_tracker
        entities whose coordinate lives in an attribute (see
        _DEVICE_TRACKER_ATTR).
        """
        eid = self.config.get(key)
        if not eid:
            return None
        state = self.hass.states.get(eid)
        if state is None:
            return None
        if eid.startswith("device_tracker.") and key in _DEVICE_TRACKER_ATTR:
            return _to_float(state.attributes.get(_DEVICE_TRACKER_ATTR[key]))
        return _to_float(state.state)
