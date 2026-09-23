# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Binary sensor platform for Clever Caravan: Power.

Provides the MQTT-derived boolean sensors (as before) plus diagnostic
connection-status sensors: MQTT connectivity and a per-BLE-device "receiving"
indicator, so BLE fallback health is visible without reading logs.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .ble_map import CONF_BLE_DEVICES, KIND_LABELS, status_triple
from .const import (
    DEV_GX,
    DEVICE_NAMES,
    DOMAIN,
    MANUFACTURER,
    SIGNAL_CONNECTION,
    VBinarySensorDef,
)
from .entity import CcpEntity, async_setup_discovery

# How often the BLE "receiving" sensors re-check freshness (seconds).
_BLE_STATUS_REFRESH = 15


def _gx_device_info(portal: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{portal}_{DEV_GX}")},
        name=DEVICE_NAMES[DEV_GX],
        manufacturer=MANUFACTURER,
        model="Cerbo GX",
    )


def _evaluate(predicate: str, value) -> bool | None:
    """Evaluate "gt:<n>" / "eq:<n>" predicates against a Venus value."""
    if value is None:
        return None
    op, _, threshold = predicate.partition(":")
    try:
        number = float(value)
        limit = float(threshold)
    except (TypeError, ValueError):
        return None
    if op == "gt":
        return number > limit
    if op == "eq":
        return number == limit
    return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]

    @callback
    def _factory(vdef, instance: str, extra) -> None:
        async_add_entities([CcpBinarySensor(data, vdef, instance)])

    async_setup_discovery(hass, entry, data, "binary_sensor", _factory)

    # Diagnostic status sensors (created once, not discovery-driven).
    status: list[BinarySensorEntity] = [CcpMqttStatus(data)]
    for cfg in entry.options.get(CONF_BLE_DEVICES, []):
        status.append(CcpBleStatus(data, cfg))
    async_add_entities(status)


class CcpBinarySensor(CcpEntity, BinarySensorEntity):
    """A boolean condition derived from a Venus dbus value."""

    def __init__(self, data, vdef: VBinarySensorDef, instance: str) -> None:
        super().__init__(data, vdef, instance, f"{vdef.key}_{instance}")
        if vdef.device_class:
            self._attr_device_class = vdef.device_class
        self._expire_unsub = None
        self._apply_value(self._hub.get(vdef.service, instance, vdef.path))

    @property
    def available(self) -> bool:
        # Available if MQTT is healthy OR the BLE fallback has a fresh reading
        # for this datapoint.
        return (self._hub.connected and self._hub.heartbeat_ok) or self._data.ble_fresh(
            self._def.service, self._instance, self._def.path
        )

    @callback
    def _apply_value(self, value) -> None:
        if value is None and self._def.none_as_zero:
            value = 0
        self._attr_is_on = _evaluate(self._def.predicate, value)
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
            self._attr_is_on = None
            self.async_write_ha_state()

        self._expire_unsub = async_call_later(self.hass, self._def.expire, _expire)

    async def async_will_remove_from_hass(self) -> None:
        if self._expire_unsub:
            self._expire_unsub()
            self._expire_unsub = None


class CcpMqttStatus(BinarySensorEntity):
    """Diagnostic: is the Venus MQTT connection up and heartbeating?

    Deliberately NOT tied to CcpEntity availability — this sensor must stay
    available so it can show 'off' when MQTT is down.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, data) -> None:
        self._data = data
        self._hub = data.hub
        portal = self._hub.portal_id
        self._attr_unique_id = f"{portal}_mqtt_connected"
        self._attr_name = "MQTT Connected"
        self._attr_device_info = _gx_device_info(portal)

    @property
    def is_on(self) -> bool:
        return self._hub.connected and self._hub.heartbeat_ok

    async def async_added_to_hass(self) -> None:
        eid = self._data.entry.entry_id
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CONNECTION.format(eid), self._refresh
            )
        )
        # Heartbeat can go stale without a connection event; re-check on a timer.
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._refresh, timedelta(seconds=30)
            )
        )

    @callback
    def _refresh(self, _arg=None) -> None:
        self.async_write_ha_state()


class CcpBleStatus(BinarySensorEntity):
    """Diagnostic: is a configured Victron BLE device currently being decoded?

    'On' means a valid advert for this device was decoded within the resolver's
    BLE TTL. BLE is broadcast, so this is 'receiving', not a connection.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, data, cfg: dict) -> None:
        self._data = data
        self._hub = data.hub
        self._cfg = cfg
        portal = self._hub.portal_id
        mac = cfg["address"]
        label = KIND_LABELS.get(cfg.get("kind"), cfg.get("kind", "device"))
        self._attr_unique_id = f"{portal}_ble_recv_{mac.replace(':', '')}"
        self._attr_name = f"Bluetooth Receiving \u2014 {label} {mac}"
        self._attr_device_info = _gx_device_info(portal)
        self._triple = status_triple(cfg)

    @property
    def is_on(self) -> bool:
        return self._data.ble_fresh(*self._triple)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._refresh, timedelta(seconds=_BLE_STATUS_REFRESH)
            )
        )

    @callback
    def _refresh(self, _now=None) -> None:
        self.async_write_ha_state()
