# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Sensor platform for Clever Caravan TPMS."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate,
    PassiveBluetoothProcessorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TPMSConfigEntry
from .entity import device_info, key
from .parser import TPMSReading

PRESSURE = SensorEntityDescription(
    key="pressure",
    device_class=SensorDeviceClass.PRESSURE,
    native_unit_of_measurement=UnitOfPressure.KPA,
    suggested_unit_of_measurement=UnitOfPressure.PSI,
    suggested_display_precision=1,
    state_class=SensorStateClass.MEASUREMENT,
)
TEMPERATURE = SensorEntityDescription(
    key="temperature",
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    suggested_display_precision=1,
    state_class=SensorStateClass.MEASUREMENT,
)
BATTERY = SensorEntityDescription(
    key="battery",
    device_class=SensorDeviceClass.BATTERY,
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
)
RSSI = SensorEntityDescription(
    key="rssi",
    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)
WHEEL = SensorEntityDescription(
    key="wheel",
    icon="mdi:tire",
    entity_category=EntityCategory.DIAGNOSTIC,
)

DESCRIPTIONS = {d.key: d for d in (PRESSURE, TEMPERATURE, BATTERY, RSSI, WHEEL)}
NAMES = {
    "pressure": "Pressure",
    "temperature": "Temperature",
    "battery": "Battery",
    "rssi": "Signal strength",
    "wheel": "Wheel position",
}


def _to_data_update(
    reading: TPMSReading | None,
) -> PassiveBluetoothDataUpdate:
    """Convert a parsed reading into entity data."""
    if reading is None:
        return PassiveBluetoothDataUpdate()
    return PassiveBluetoothDataUpdate(
        devices={None: device_info(reading)},
        entity_descriptions={key(k): d for k, d in DESCRIPTIONS.items()},
        entity_names={key(k): n for k, n in NAMES.items()},
        entity_data={
            key("pressure"): reading.pressure_kpa,
            key("temperature"): reading.temperature_c,
            key("battery"): reading.battery_pct,
            key("wheel"): reading.wheel,
            key("rssi"): reading.rssi,
        },
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TPMSConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up TPMS sensors."""
    coordinator = entry.runtime_data
    processor = PassiveBluetoothDataProcessor(_to_data_update)
    entry.async_on_unload(
        processor.async_add_entities_listener(TPMSSensorEntity, async_add_entities)
    )
    entry.async_on_unload(coordinator.async_register_processor(processor))


class TPMSSensorEntity(
    PassiveBluetoothProcessorEntity[PassiveBluetoothDataProcessor],
    SensorEntity,
):
    """A Safety Sam TPMS sensor value."""

    @property
    def native_value(self) -> float | int | None:
        """Return the sensor value."""
        return self.processor.entity_data.get(self.entity_key)
