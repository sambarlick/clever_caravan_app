# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Cover platform for Clever Caravan: Waymote.

An awning is three outputs - Power, Extend, Retract - presented as one cover.

Behaviour matches the hardware: a direction relay switched on runs the motor to
its end stop; switching that relay off stops it wherever it is. There is no
position feedback, so the cover is assumed-state.

Rules:
  - Power is switched on before a direction relay, and the opposite direction is
    always switched off first, so Extend and Retract are never on together.
  - Stop drops both direction relays. Whether it also drops Power is set on the
    integration's Configure screen (default: leave power on, so a follow-up
    adjustment does not wait for it).
  - Power is dropped automatically after an idle period (default 3 minutes).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from . import WaymoteConfigEntry
from .const import (
    AVAILABILITY_TOPIC,
    STATUS_TOPIC,
    COMBO_AWNING,
    CONF_AWNING_POWER_OFF_MINUTES,
    CONF_AWNING_STOP_CUTS_POWER,
    CONTROL_TOPIC,
    DEFAULT_AWNING_POWER_OFF_MINUTES,
    DEFAULT_AWNING_STOP_CUTS_POWER,
    DOMAIN,
    get_combos,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaymoteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[CoverEntity] = []
    for index, combo in enumerate(get_combos(entry)):
        if combo.get("type") == COMBO_AWNING:
            entities.append(WaymoteAwningCover(coordinator, entry, combo, index))
    async_add_entities(entities)


class WaymoteAwningCover(CoverEntity):
    """Power + Extend + Retract presented as one awning."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_assumed_state = True
    _attr_device_class = CoverDeviceClass.AWNING
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(self, coordinator, entry, combo: dict, index: int) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._power = int(combo["power"])
        self._extend = int(combo["extend"])
        self._retract = int(combo["retract"])
        base = coordinator.entry.unique_id or coordinator.entry.entry_id
        self._attr_unique_id = f"{base}_awning_{index}_{self._power}"
        self._attr_name = combo.get("name") or f"Awning {index + 1}"
        self._attr_icon = "mdi:awning-outline"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, base)})
        self._opening = False
        self._closing = False
        self._closed: bool | None = None
        self._available = True
        self._power_on = False
        self._cancel_power_off = None

    # --- settings ----------------------------------------------------------

    @property
    def _power_off_minutes(self) -> int:
        return int(
            self._entry.options.get(
                CONF_AWNING_POWER_OFF_MINUTES, DEFAULT_AWNING_POWER_OFF_MINUTES
            )
        )

    @property
    def _stop_cuts_power(self) -> bool:
        return bool(
            self._entry.options.get(
                CONF_AWNING_STOP_CUTS_POWER, DEFAULT_AWNING_STOP_CUTS_POWER
            )
        )

    # --- state -------------------------------------------------------------

    @property
    def is_opening(self) -> bool:
        return self._opening

    @property
    def is_closing(self) -> bool:
        return self._closing

    @property
    def is_closed(self) -> bool | None:
        return self._closed

    @property
    def available(self) -> bool:
        return self._available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Power state shown on the cover, so both read as one device.

        Read-only here - control is the awning's own Power switch.
        """
        return {"power": "on" if self._power_on else "off"}

    # --- mqtt --------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _availability(msg: mqtt.ReceiveMessage) -> None:
            self._available = msg.payload.strip() == "online"
            self.async_write_ha_state()

        self.async_on_remove(
            await mqtt.async_subscribe(self.hass, AVAILABILITY_TOPIC, _availability)
        )

        @callback
        def _power_status(msg: mqtt.ReceiveMessage) -> None:
            payload = msg.payload.strip().upper()
            if payload in ("ON", "OFF"):
                self._power_on = payload == "ON"
                self.async_write_ha_state()

        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, STATUS_TOPIC.format(n=self._power), _power_status
            )
        )

    async def _publish(self, channel: int, on: bool) -> None:
        if channel == self._power:
            self._power_on = on
        await mqtt.async_publish(
            self.hass, CONTROL_TOPIC.format(n=channel), "ON" if on else "OFF",
            qos=1, retain=True,
        )

    # --- power timer -------------------------------------------------------

    def _cancel_timer(self) -> None:
        if self._cancel_power_off is not None:
            self._cancel_power_off()
            self._cancel_power_off = None

    def _schedule_power_off(self) -> None:
        """Drop power after the idle period, so it is not left live."""
        self._cancel_timer()
        minutes = self._power_off_minutes
        if minutes <= 0:
            return

        async def _power_off(_now) -> None:
            self._cancel_power_off = None
            # Drop the direction relays too: leaving one live would mean a later
            # manual power-on starts the motor by itself.
            await self._publish(self._extend, False)
            await self._publish(self._retract, False)
            await self._publish(self._power, False)

        self._cancel_power_off = async_call_later(
            self.hass, minutes * 60, _power_off
        )

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_timer()
        await super().async_will_remove_from_hass()

    # --- commands ----------------------------------------------------------

    async def _move(self, direction: int, opposite: int) -> None:
        self._cancel_timer()
        await self._publish(opposite, False)
        await self._publish(self._power, True)
        await self._publish(direction, True)

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._move(self._extend, self._retract)
        # The motor runs to its end stop and nothing reports back, so we record
        # the requested end state rather than a transient "opening".
        self._opening = self._closing = False
        self._closed = False
        self._schedule_power_off()
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._move(self._retract, self._extend)
        self._opening = self._closing = False
        self._closed = True
        self._schedule_power_off()
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._publish(self._extend, False)
        await self._publish(self._retract, False)
        if self._stop_cuts_power:
            self._cancel_timer()
            await self._publish(self._power, False)
        else:
            self._schedule_power_off()
        # Stopped part-way: not fully closed as far as we can tell.
        if self._closing:
            self._closed = None
        self._opening = self._closing = False
        self.async_write_ha_state()
