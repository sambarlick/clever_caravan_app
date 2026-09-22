# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Binary sensor platform for Clever Caravan TPMS (leak alarm)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TPMSConfigEntry
from .entity import device_info, key
from .parser import TPMSReading

ALARM = BinarySensorEntityDescription(
    key="alarm",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


def _to_data_update(
    reading: TPMSReading | None,
) -> PassiveBluetoothDataUpdate:
    if reading is None:
        return PassiveBluetoothDataUpdate()
    return PassiveBluetoothDataUpdate(
        devices={None: device_info(reading)},
        entity_descriptions={key("alarm"): ALARM},
        entity_names={key("alarm"): "Pressure alarm"},
        entity_data={key("alarm"): reading.alarm},
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TPMSConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TPMS binary sensors."""
    coordinator = entry.runtime_data
    processor = PassiveBluetoothDataProcessor(_to_data_update)
    entry.async_on_unload(
        processor.async_add_entities_listener(
            TPMSBinarySensorEntity, async_add_entities
        )
    )
    entry.async_on_unload(coordinator.async_register_processor(processor))


class TPMSBinarySensorEntity(
    PassiveBluetoothProcessorEntity[PassiveBluetoothDataProcessor],
    BinarySensorEntity,
):
    """Leak / fast-deflation alarm reported by the sensor."""

    @property
    def is_on(self) -> bool | None:
        """Return True if the sensor is reporting an alarm."""
        return self.processor.entity_data.get(self.entity_key)
