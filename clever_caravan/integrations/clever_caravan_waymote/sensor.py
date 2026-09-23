# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Diagnostic sensors for Clever Caravan: Waymote (bridge + CAN status)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaymoteConfigEntry
from .entity import WaymoteBridgeEntity


@dataclass(frozen=True, kw_only=True)
class WaymoteSensorSpec:
    key: str
    name: str
    topic: str
    icon: str
    numeric: bool = False
    unit: str | None = None


SENSORS: tuple[WaymoteSensorSpec, ...] = (
    WaymoteSensorSpec(key="can_state", name="CAN Bus State",
                      topic="Waymote/CAN/State", icon="mdi:serial-port"),
    WaymoteSensorSpec(key="can_bus_active", name="CAN Bus Active",
                      topic="Waymote/CAN/BusActive", icon="mdi:transit-connection-variant"),
    WaymoteSensorSpec(key="mismatch_count", name="CAN Bus Mismatch Count",
                      topic="Waymote/Status/MismatchCount", icon="mdi:alert-circle-outline", numeric=True),
    WaymoteSensorSpec(key="status_warning", name="Waymote Status Warning",
                      topic="Waymote/Warning/StatusLost", icon="mdi:alert-circle"),
    WaymoteSensorSpec(key="reset_status", name="CAN Reset Status",
                      topic="Waymote/CAN/ResetStatus", icon="mdi:refresh-circle"),
    WaymoteSensorSpec(key="busoff_count", name="CAN Bus Off Count",
                      topic="Waymote/CAN/BusOffCount", icon="mdi:alert", numeric=True),
    WaymoteSensorSpec(key="restarts", name="CAN Restarts",
                      topic="Waymote/CAN/Restarts", icon="mdi:restart", numeric=True),
    WaymoteSensorSpec(key="rx_count", name="CAN RX Count",
                      topic="Waymote/CAN/RxCount", icon="mdi:arrow-down", numeric=True),
    WaymoteSensorSpec(key="tx_count", name="CAN TX Count",
                      topic="Waymote/CAN/TxCount", icon="mdi:arrow-up", numeric=True),
    WaymoteSensorSpec(key="rx_errors", name="CAN RX Errors",
                      topic="Waymote/CAN/RxErrors", icon="mdi:alert", numeric=True),
    WaymoteSensorSpec(key="tx_errors", name="CAN TX Errors",
                      topic="Waymote/CAN/TxErrors", icon="mdi:alert", numeric=True),
    WaymoteSensorSpec(key="last_rx", name="CAN Last RX",
                      topic="Waymote/CAN/LastRx", icon="mdi:timer-outline", numeric=True, unit=UnitOfTime.SECONDS),
    WaymoteSensorSpec(key="last_tx", name="CAN Last TX",
                      topic="Waymote/CAN/LastTx", icon="mdi:timer-outline", numeric=True, unit=UnitOfTime.SECONDS),
    WaymoteSensorSpec(key="last_waymote_rx", name="CAN Last Waymote RX",
                      topic="Waymote/CAN/LastWaymoteRx", icon="mdi:timer-outline", numeric=True, unit=UnitOfTime.SECONDS),
)


def coerce_number(payload: str):
    """Return an int/float for a numeric payload, else None."""
    try:
        value = float(payload)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaymoteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(WaymoteSensor(coordinator, spec) for spec in SENSORS)


class WaymoteSensor(WaymoteBridgeEntity, SensorEntity):
    def __init__(self, coordinator, spec: WaymoteSensorSpec) -> None:
        super().__init__(
            coordinator,
            key=spec.key,
            name=spec.name,
            state_topic=spec.topic,
            icon=spec.icon,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        self._spec = spec
        if spec.unit:
            self._attr_native_unit_of_measurement = spec.unit

    @property
    def native_value(self):
        if self._payload is None:
            return None
        if self._spec.numeric:
            return coerce_number(self._payload)
        return self._payload
