# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Config flow for Clever Caravan: Location."""

from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.helpers import selector

from .const import (
    CONF_ELEVATION_ENTITY,
    CONF_LATITUDE_ENTITY,
    CONF_LONGITUDE_ENTITY,
    CONF_SOURCE,
    CONF_SPEED_ENTITY,
    CONF_USB_BAUDRATE,
    CONF_USB_DEVICE,
    DEFAULT_BAUDRATE,
    DOMAIN,
    SOURCE_ENTITY,
    SOURCE_MANUAL,
    SOURCE_USB,
    SOURCES,
)


def _scan_serial_devices() -> list[str]:
    """List USB serial devices by stable id.

    /dev/serial/by-id/* paths are stable across reboots and survive
    different USB ports — better than /dev/ttyACM0 which can change.
    """
    by_id = "/dev/serial/by-id"
    if not os.path.isdir(by_id):
        return []
    try:
        return sorted(
            os.path.join(by_id, name)
            for name in os.listdir(by_id)
        )
    except OSError:
        return []


class CleverCaravanLocationConfigFlow(ConfigFlow, domain=DOMAIN):
    """Two-step flow: pick source type, then pick source-specific config.

    The same two source-specific steps (usb / entities) back both the
    initial setup and the reconfigure flow. On initial setup they call
    async_create_entry; on reconfigure they update the existing entry in
    place and reload, preserving entity IDs and history.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._source_type: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # Single instance only — two configs would fight over zone.home.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            self._source_type = user_input[CONF_SOURCE]
            if self._source_type == SOURCE_USB:
                return await self.async_step_usb()
            return await self.async_step_entities()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_SOURCE, default=SOURCE_USB): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=SOURCES,
                        translation_key="source",
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the source (or its config) on the existing entry.

        Re-runs the same source picker, defaulted to the current source,
        then routes into the shared usb/entities step. Those steps detect
        the reconfigure context and update-and-reload instead of creating
        a new entry.
        """
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            self._source_type = user_input[CONF_SOURCE]
            if self._source_type == SOURCE_USB:
                return await self.async_step_usb()
            return await self.async_step_entities()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SOURCE,
                    default=entry.data.get(CONF_SOURCE, SOURCE_USB),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=SOURCES,
                        translation_key="source",
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
        )

    async def async_step_usb(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """USB GPS configuration: pick device + baudrate."""
        detected = await self.hass.async_add_executor_job(_scan_serial_devices)

        if user_input is not None:
            data = {
                CONF_SOURCE: SOURCE_USB,
                CONF_USB_DEVICE: user_input[CONF_USB_DEVICE],
                CONF_USB_BAUDRATE: int(user_input[CONF_USB_BAUDRATE]),
            }
            return self._finish(title="Clever Caravan: Location (USB GPS)", data=data)

        # Prefill from the existing entry when reconfiguring an already-USB
        # source. custom_value=True lets the user type a path even when
        # nothing's auto-detected (e.g. dongle plugged in after onboarding
        # starts, or the previously-configured device isn't present now).
        current = self._reconfigure_data()
        device_default = current.get(CONF_USB_DEVICE) or (detected[0] if detected else "")
        baud_default = current.get(CONF_USB_BAUDRATE, DEFAULT_BAUDRATE)

        return self.async_show_form(
            step_id="usb",
            data_schema=vol.Schema({
                vol.Required(CONF_USB_DEVICE, default=device_default): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=detected,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                ),
                vol.Required(CONF_USB_BAUDRATE, default=baud_default): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=2400, max=921600, step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }),
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entity-based or manual source: pick the entities.

        For a device_tracker (e.g. the Companion app on an iPad), point
        both latitude and longitude at the same device_tracker entity —
        the source reads the coordinates from its attributes.
        """
        if user_input is not None:
            data = {CONF_SOURCE: self._source_type, **user_input}
            title = {
                SOURCE_ENTITY: "Clever Caravan: Location (Entity-based)",
                SOURCE_MANUAL: "Clever Caravan: Location (Manual)",
            }[self._source_type or SOURCE_ENTITY]
            return self._finish(title=title, data=data)

        current = self._reconfigure_data()
        sensor_or_input = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor", "input_number", "device_tracker"],
            )
        )

        def _field(key: str, required: bool) -> vol.Marker:
            marker = vol.Required if required else vol.Optional
            if current.get(key) is not None:
                return marker(key, default=current[key])
            return marker(key)

        return self.async_show_form(
            step_id="entities",
            data_schema=vol.Schema({
                _field(CONF_LATITUDE_ENTITY, True): sensor_or_input,
                _field(CONF_LONGITUDE_ENTITY, True): sensor_or_input,
                _field(CONF_ELEVATION_ENTITY, False): sensor_or_input,
                _field(CONF_SPEED_ENTITY, False): sensor_or_input,
            }),
            description_placeholders={"source": self._source_type or ""},
        )

    def _reconfigure_data(self) -> dict[str, Any]:
        """Existing entry data to prefill from, or empty on fresh setup.

        Only prefills when reconfiguring and the source type is unchanged —
        switching source (e.g. USB -> Entity) starts the new step blank,
        since the old source's fields don't apply.
        """
        if self.source != SOURCE_RECONFIGURE:
            return {}
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_SOURCE) != self._source_type:
            return {}
        return dict(entry.data)

    def _finish(self, *, title: str, data: dict[str, Any]) -> ConfigFlowResult:
        """Create the entry, or update-and-reload it when reconfiguring.

        Title is intentionally left untouched on reconfigure so a
        user-renamed entry keeps its name.
        """
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data=data,
            )
        return self.async_create_entry(title=title, data=data)
