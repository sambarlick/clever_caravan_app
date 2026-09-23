# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Sensor platform for Clever Caravan: Power."""
from __future__ import annotations
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from .const import (
    AGG_SOLAR_ENERGY,
    AGG_SOLAR_POWER,
    AGG_SOLAR_YIELD_TODAY,
    CONF_FLOW_DEADBAND,
    DEFAULT_FLOW_DEADBAND,
    DEV_SOLAR,
    DOMAIN,
    VSensorDef,
)
from .entity import CcpEntity, async_setup_discovery
_LOGGER = logging.getLogger(__name__)
def _ttg_text(value) -> str:
    """Format Venus TimeToGo seconds the Clever Caravan way."""
    if value is None:
        return "For Ever and Ever!"
    total = int(value)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''} {hours} hour{'s' if hours != 1 else ''}"
    if hours >= 1:
        return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
    return f"{minutes} minute{'s' if minutes != 1 else ''}"
TRANSFORMS = {
    "ttg_text": _ttg_text,
    "m3_to_l": lambda v: round(float(v) * 1000, 1) if v is not None else None,
    # flow_direction is handled specially in CcpSensor._apply_value because it
    # needs the per-install deadband from entry.options; the placeholder keeps
    # it a recognised transform key.
    "flow_direction": lambda v: v,
}
async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    aggregates_added = False
    @callback
    def _factory(vdef, instance: str, extra) -> None:
        nonlocal aggregates_added
        entities = [CcpSensor(data, vdef, instance, f"{vdef.key}_{instance}")]
        # First solar charger seen -> create the fleet aggregates.
        if not aggregates_added and vdef.service == "solarcharger":
            aggregates_added = True
            entities.append(CcpSolarAggregate(data, AGG_SOLAR_POWER))
            entities.append(CcpSolarAggregate(data, AGG_SOLAR_ENERGY))
            entities.append(CcpSolarAggregate(data, AGG_SOLAR_YIELD_TODAY))
        async_add_entities(entities)
    async_setup_discovery(hass, entry, data, "sensor", _factory)
class CcpSensor(CcpEntity, SensorEntity):
    """A sensor mapped from a Venus dbus path."""
    def __init__(self, data, vdef: VSensorDef, instance: str, value_key: str) -> None:
        super().__init__(data, vdef, instance, value_key)
        if vdef.unit:
            self._attr_native_unit_of_measurement = vdef.unit
        if vdef.device_class:
            self._attr_device_class = vdef.device_class
        if vdef.state_class:
            self._attr_state_class = vdef.state_class
        if vdef.suggested_precision is not None:
            self._attr_suggested_display_precision = vdef.suggested_precision
        self._expire_unsub = None
        self._apply_value(self._hub.get(vdef.service, instance, vdef.path))

    @property
    def available(self) -> bool:
        # Available if MQTT is healthy OR the BLE fallback has a fresh reading
        # for this datapoint. Re-evaluated on every value/connection update.
        return (self._hub.connected and self._hub.heartbeat_ok) or self._data.ble_fresh(
            self._def.service, self._instance, self._def.path
        )

    @callback
    def _flow_direction(self, value):
        """Charging / Discharging / Idle with a per-install deadband."""
        if value is None:
            return None
        try:
            watts = float(value)
        except (TypeError, ValueError):
            return None
        deadband = abs(
            self._data.entry.options.get(CONF_FLOW_DEADBAND, DEFAULT_FLOW_DEADBAND)
        )
        if watts > deadband:
            self._attr_icon = "mdi:battery-charging"
            return "Charging"
        if watts < -deadband:
            self._attr_icon = "mdi:battery-minus"
            return "Discharging"
        self._attr_icon = "mdi:battery"
        return "Idle"
    @callback
    def _apply_value(self, value) -> None:
        vdef = self._def
        if value is None and getattr(vdef, "none_as_zero", False):
            value = 0
        if vdef.options_map is not None:
            try:
                value = vdef.options_map.get(int(value), "Unknown")
            except (TypeError, ValueError):
                value = None
        elif vdef.transform == "flow_direction":
            value = self._flow_direction(value)
        elif vdef.transform:
            try:
                value = TRANSFORMS[vdef.transform](value)
            except (TypeError, ValueError):
                value = None
        self._attr_native_value = value
        self._schedule_expiry()
    @callback
    def _schedule_expiry(self) -> None:
        if not self._def.expire or not self.hass:
            return
        if self._expire_unsub:
            self._expire_unsub()
        @callback
        def _expire(_now) -> None:
            self._expire_unsub = None
            self._attr_native_value = None
            self.async_write_ha_state()
        self._expire_unsub = async_call_later(self.hass, self._def.expire, _expire)
    async def async_will_remove_from_hass(self) -> None:
        if self._expire_unsub:
            self._expire_unsub()
            self._expire_unsub = None
_AGG_META = {
    AGG_SOLAR_POWER: VSensorDef(
        AGG_SOLAR_POWER, "solarcharger", "Yield/Power", "Total Solar Power",
        DEV_SOLAR, "W", "power", "measurement", "mdi:solar-power",
        suggested_precision=0,
    ),
    AGG_SOLAR_ENERGY: VSensorDef(
        AGG_SOLAR_ENERGY, "solarcharger", "Yield/User", "Total Solar Energy",
        DEV_SOLAR, "kWh", "energy", "total_increasing", "mdi:solar-power",
        suggested_precision=2,
    ),
    AGG_SOLAR_YIELD_TODAY: VSensorDef(
        AGG_SOLAR_YIELD_TODAY, "solarcharger", "History/Daily/0/Yield",
        "Total Solar Yield Today",
        DEV_SOLAR, "kWh", "energy", "measurement", "mdi:solar-power",
        suggested_precision=2,
    ),
}
class CcpSolarAggregate(CcpEntity, SensorEntity):
    """Sum of a value across every discovered solar charger."""
    def __init__(self, data, agg_key: str) -> None:
        vdef = _AGG_META[agg_key]
        # Subscribes to the dedicated aggregate signal sent by the hub glue
        # whenever ANY charger's yield updates — chargers discovered later
        # are included automatically.
        super().__init__(data, vdef, "all", "sc_aggregate")
        self._attr_unique_id = f"{self._hub.portal_id}_{agg_key}"
        self._attr_native_unit_of_measurement = vdef.unit
        self._attr_device_class = vdef.device_class
        self._attr_state_class = vdef.state_class
        self._attr_suggested_display_precision = vdef.suggested_precision
        self._recompute()

    @property
    def available(self) -> bool:
        # Available if MQTT is healthy, or any solar charger has a fresh BLE
        # reading for this aggregate's path during an MQTT outage.
        if self._hub.connected and self._hub.heartbeat_ok:
            return True
        return any(
            self._data.ble_fresh("solarcharger", inst, self._def.path)
            for inst in self._hub.instances_of("solarcharger")
        )

    @callback
    def _apply_value(self, value) -> None:
        self._recompute()
    @callback
    def _recompute(self) -> None:
        total = 0.0
        seen = False
        for instance in self._hub.instances_of("solarcharger"):
            value = self._hub.get("solarcharger", instance, self._def.path)
            if value is None:
                continue
            try:
                total += float(value)
                seen = True
            except (TypeError, ValueError):
                continue
        self._attr_native_value = round(total, 3) if seen else None
