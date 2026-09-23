# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Button platform for Clever Caravan: Power (Cerbo GX reboot, MQTT + SSH)."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SSH_KEY, DEFAULT_SSH_KEY, DEV_GX, DEVICE_NAMES, DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CcpMqttRebootButton(data), CcpSshRebootButton(data)])


class _RebootBase(ButtonEntity):
    _attr_should_poll = False
    _attr_icon = "mdi:restart"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, data) -> None:
        self._data = data
        self._hub = data.hub
        portal = self._hub.portal_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{portal}_{DEV_GX}")},
            name=DEVICE_NAMES[DEV_GX],
            manufacturer=MANUFACTURER,
            model="Cerbo GX",
        )


class CcpMqttRebootButton(_RebootBase):
    """Reboots the GX device over MQTT (Venus OS 3.x+)."""

    _attr_name = "Reboot (MQTT)"

    def __init__(self, data) -> None:
        super().__init__(data)
        # Keep the pre-0.1.3 unique_id so the existing entity is renamed,
        # not orphaned.
        self._attr_unique_id = f"{self._hub.portal_id}_reboot"

    @property
    def available(self) -> bool:
        return self._hub.connected

    async def async_press(self) -> None:
        self._hub.set_value("platform", "0", "Device/Reboot", 1)


class CcpSshRebootButton(_RebootBase):
    """Reboots the GX device over SSH — works even when MQTT is down."""

    _attr_name = "Reboot (SSH)"
    # Deliberately always available: this is the fallback path.

    def __init__(self, data) -> None:
        super().__init__(data)
        self._attr_unique_id = f"{self._hub.portal_id}_reboot_ssh"
        self._host = data.entry.data[CONF_HOST]
        self._key = data.entry.options.get(CONF_SSH_KEY, DEFAULT_SSH_KEY)

    async def async_press(self) -> None:
        cmd = [
            "ssh",
            "-i", self._key,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            f"root@{self._host}",
            "reboot",
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        # 'reboot' usually drops the connection — 255 with a closed session
        # is success in practice. Only log genuinely unexpected output.
        if process.returncode not in (0, 255):
            _LOGGER.error(
                "SSH reboot of %s failed (rc=%s): %s",
                self._host, process.returncode, stderr.decode(errors="replace").strip(),
            )
