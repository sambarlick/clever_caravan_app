# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Config flow for Clever Caravan TPMS."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN
from .parser import parse, short_address, supported


def _title(service_info: BluetoothServiceInfoBleak) -> str:
    reading = parse(service_info)
    suffix = short_address(service_info.address)
    if reading is not None:
        return f"Safety Sam TPMS Wheel {reading.wheel} ({suffix})"
    return f"Safety Sam TPMS ({suffix})"


class TPMSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Safety Sam TPMS sensors."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a discovered sensor."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not supported(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered sensor."""
        assert self._discovery_info is not None
        title = _title(self._discovery_info)
        if user_input is not None:
            return self.async_create_entry(title=title, data={})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": title},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup: pick from currently visible sensors."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title(self._discovered[address]), data={}
            )

        current = self._async_current_ids(include_ignore=False)
        for service_info in async_discovered_service_info(self.hass, False):
            address = service_info.address
            if address in current or not supported(service_info):
                continue
            self._discovered[address] = service_info

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: _title(info)
                            for address, info in self._discovered.items()
                        }
                    )
                }
            ),
        )
