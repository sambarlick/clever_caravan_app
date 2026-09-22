# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Sensor entities for Clever Caravan Location."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import DEGREE, UnitOfLength, UnitOfSpeed
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_SOURCE,
    DOMAIN,
    DOP_TO_METRES,
    FIX_MODE_2D,
    FIX_MODE_3D,
    FIX_MODE_NO_FIX,
    FIX_MODE_OPTIONS,
    FIX_QUALITY_LABELS,
    FIX_QUALITY_OPTIONS,
    GRADIENT_OPTIONS,
    HEADING_DIRECTIONS,
    SIGNAL_ABS_UPDATED,
    SIGNAL_GEOCODE_UPDATED,
    SIGNAL_LOCATION_UPDATED,
    SIGNAL_METEOSTAT_UPDATED,
    SIGNAL_WIKI_UPDATED,
    SOURCE_USB,
    STATUS_OPTIONS,
)
from .coordinator import CaravanLocationCoordinator, get_coordinator

_LOGGER = logging.getLogger(__name__)


def _degrees_to_cardinal(deg: float) -> str:
    return HEADING_DIRECTIONS[int((deg + 11.25) / 22.5) % 16]


def _heading_value(c):
    if c.latest is None or c.latest.heading_deg is None:
        return None
    return _degrees_to_cardinal(c.latest.heading_deg)


def _bearing_value(c):
    if c.latest is None or c.latest.heading_deg is None:
        return None
    return round(c.latest.heading_deg, 1)


def _fix_quality_value(c):
    if c.latest is None or c.latest.fix_quality is None:
        return None
    return FIX_QUALITY_LABELS.get(c.latest.fix_quality)


def _fix_mode_value(c):
    if c.latest is None or c.latest.fix_mode is None:
        return None
    return {1: FIX_MODE_NO_FIX, 2: FIX_MODE_2D, 3: FIX_MODE_3D}.get(
        c.latest.fix_mode
    )


def _accuracy_h_value(c):
    if c.latest is None or c.latest.hdop is None:
        return None
    return round(c.latest.hdop * DOP_TO_METRES, 1)


def _accuracy_v_value(c):
    if c.latest is None or c.latest.vdop is None:
        return None
    return round(c.latest.vdop * DOP_TO_METRES, 1)


@dataclass(frozen=True, kw_only=True)
class CaravanSensorDescription(SensorEntityDescription):
    """Sensor description with a value getter against the coordinator."""

    value_fn: Callable[[CaravanLocationCoordinator], object]
    update_signal: str = SIGNAL_LOCATION_UPDATED


SENSORS: tuple[CaravanSensorDescription, ...] = (
    CaravanSensorDescription(
        key="latitude", translation_key="latitude", icon="mdi:latitude",
        suggested_display_precision=6,
        value_fn=lambda c: c.display_latitude,
    ),
    CaravanSensorDescription(
        key="longitude", translation_key="longitude", icon="mdi:longitude",
        suggested_display_precision=6,
        value_fn=lambda c: c.display_longitude,
    ),
    CaravanSensorDescription(
        key="elevation", translation_key="elevation", icon="mdi:elevation-rise",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.display_elevation,
    ),
    CaravanSensorDescription(
        key="speed", translation_key="speed", icon="mdi:speedometer",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.display_speed,
    ),
    CaravanSensorDescription(
        key="heading", translation_key="heading", icon="mdi:compass",
        device_class=SensorDeviceClass.ENUM,
        options=HEADING_DIRECTIONS,
        value_fn=_heading_value,
    ),
    CaravanSensorDescription(
        key="bearing", translation_key="bearing", icon="mdi:compass-outline",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_bearing_value,
    ),
    CaravanSensorDescription(
        key="status", translation_key="status", icon="mdi:caravan",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        value_fn=lambda c: c.status,
    ),
    CaravanSensorDescription(
        key="gradient", translation_key="gradient", icon="mdi:slope-uphill",
        device_class=SensorDeviceClass.ENUM,
        options=GRADIENT_OPTIONS,
        value_fn=lambda c: c.gradient,
    ),
    CaravanSensorDescription(
        key="climb_rate", translation_key="climb_rate", icon="mdi:slope-uphill",
        native_unit_of_measurement="m/s",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda c: c.display_climb_ms,
    ),
    CaravanSensorDescription(
        key="fix_quality", translation_key="fix_quality",
        icon="mdi:crosshairs-gps",
        device_class=SensorDeviceClass.ENUM,
        options=FIX_QUALITY_OPTIONS,
        value_fn=_fix_quality_value,
    ),
    CaravanSensorDescription(
        key="fix_mode", translation_key="fix_mode", icon="mdi:crosshairs",
        device_class=SensorDeviceClass.ENUM,
        options=FIX_MODE_OPTIONS,
        value_fn=_fix_mode_value,
    ),
    CaravanSensorDescription(
        key="satellites_used", translation_key="satellites_used",
        icon="mdi:satellite-uplink", native_unit_of_measurement="sat",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.latest.satellites_used if c.latest else None,
    ),
    CaravanSensorDescription(
        key="satellites_visible", translation_key="satellites_visible",
        icon="mdi:satellite-variant", native_unit_of_measurement="sat",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.latest.satellites_visible if c.latest else None,
    ),
    CaravanSensorDescription(
        key="hdop", translation_key="hdop", icon="mdi:target",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda c: c.latest.hdop if c.latest else None,
    ),
    CaravanSensorDescription(
        key="accuracy_horizontal", translation_key="accuracy_horizontal",
        icon="mdi:target-variant",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.display_accuracy_h,
    ),
    CaravanSensorDescription(
        key="accuracy_vertical", translation_key="accuracy_vertical",
        icon="mdi:target-variant",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.display_accuracy_v,
    ),
    CaravanSensorDescription(
        key="gps_atomic_time", translation_key="gps_atomic_time", icon="mdi:clock-digital",
        value_fn=lambda c: (
            c.latest.gps_time.strftime("%Y-%m-%d %H:%M:%S UTC")
            if hasattr(c.latest.gps_time, "strftime")
            else str(c.latest.gps_time).replace("T", " ")[:19] + " UTC"
        ) if c.latest and c.latest.gps_time else None,
    ),
    CaravanSensorDescription(
        key="city", translation_key="city", icon="mdi:city",
        update_signal=SIGNAL_GEOCODE_UPDATED,
        value_fn=lambda c: c.geocode.city if c.geocode else None,
    ),
    CaravanSensorDescription(
        key="state", translation_key="state", icon="mdi:map",
        update_signal=SIGNAL_GEOCODE_UPDATED,
        value_fn=lambda c: c.geocode.state if c.geocode else None,
    ),
    CaravanSensorDescription(
        key="country", translation_key="country", icon="mdi:earth",
        update_signal=SIGNAL_GEOCODE_UPDATED,
        value_fn=lambda c: c.geocode.country if c.geocode else None,
    ),
    CaravanSensorDescription(
        key="postcode", translation_key="postcode", icon="mdi:mailbox",
        update_signal=SIGNAL_GEOCODE_UPDATED,
        value_fn=lambda c: c.geocode.postcode if c.geocode else None,
    ),
    CaravanSensorDescription(
        key="current_location", translation_key="current_location",
        icon="mdi:map-marker",
        update_signal=SIGNAL_GEOCODE_UPDATED,
        value_fn=lambda c: (
            f"{c.geocode.city}, {c.geocode.state_short}"
            if c.geocode and c.geocode.city and c.geocode.state_short
            else (c.geocode.city if c.geocode and c.geocode.city else None)
        ),
    ),
    CaravanSensorDescription(
        key="population", translation_key="population", icon="mdi:account-group",
        native_unit_of_measurement="people",
        state_class=SensorStateClass.MEASUREMENT,
        update_signal=SIGNAL_ABS_UPDATED,
        value_fn=lambda c: c.abs_data.population if c.abs_data else None,
    ),
    CaravanSensorDescription(
        key="statistical_area", translation_key="statistical_area",
        icon="mdi:map-marker-radius",
        update_signal=SIGNAL_ABS_UPDATED,
        value_fn=lambda c: c.abs_data.sal_name if c.abs_data else None,
    ),
    CaravanSensorDescription(
        key="statistical_area_size", translation_key="statistical_area_size",
        icon="mdi:vector-square",
        native_unit_of_measurement="km²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        update_signal=SIGNAL_ABS_UPDATED,
        value_fn=lambda c: c.abs_data.area_km2 if c.abs_data else None,
    ),
    CaravanSensorDescription(
        key="population_density", translation_key="population_density",
        icon="mdi:account-multiple",
        native_unit_of_measurement="people/km²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        update_signal=SIGNAL_ABS_UPDATED,
        value_fn=lambda c: c.abs_data.population_density if c.abs_data else None,
    ),
    CaravanSensorDescription(
        key="wikipedia_summary", translation_key="wikipedia_summary",
        icon="mdi:text-box-outline",
        update_signal=SIGNAL_WIKI_UPDATED,
        value_fn=lambda c: (
            (c.wiki_data.extract or "")[:255]
            if c.wiki_data and c.wiki_data.extract
            else None
        ),
    ),
    CaravanSensorDescription(
        key="climate_mean_max", translation_key="climate_mean_max",
        icon="mdi:thermometer-high",
        native_unit_of_measurement="°C",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        update_signal=SIGNAL_METEOSTAT_UPDATED,
        value_fn=lambda c: c.meteostat_data.mean_max_c if c.meteostat_data else None,
    ),
    CaravanSensorDescription(
        key="climate_mean_min", translation_key="climate_mean_min",
        icon="mdi:thermometer-low",
        native_unit_of_measurement="°C",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        update_signal=SIGNAL_METEOSTAT_UPDATED,
        value_fn=lambda c: c.meteostat_data.mean_min_c if c.meteostat_data else None,
    ),
    CaravanSensorDescription(
        key="climate_mean_temp", translation_key="climate_mean_temp",
        icon="mdi:thermometer",
        native_unit_of_measurement="°C",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        update_signal=SIGNAL_METEOSTAT_UPDATED,
        value_fn=lambda c: c.meteostat_data.mean_temp_c if c.meteostat_data else None,
    ),
    CaravanSensorDescription(
        key="climate_monthly_rainfall", translation_key="climate_monthly_rainfall",
        icon="mdi:weather-rainy",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        update_signal=SIGNAL_METEOSTAT_UPDATED,
        value_fn=lambda c: (
            c.meteostat_data.monthly_rainfall_mm if c.meteostat_data else None
        ),
    ),
)


# Sensor keys that only make sense on a USB GPS source. Disabled by
# default on Entity-source and Manual installs — they're either always
# unavailable (no NMEA data feed) or actively misleading (heading/climb
# from a slow Starlink poll).
USB_ONLY_KEYS: frozenset[str] = frozenset({
    "fix_quality",
    "fix_mode",
    "satellites_used",
    "satellites_visible",
    "hdop",
    "accuracy_horizontal",
    "accuracy_vertical",
    "gps_atomic_time",
})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = get_coordinator(hass, entry.entry_id)
    is_usb = entry.data.get(CONF_SOURCE) == SOURCE_USB
    async_add_entities(
        CaravanSensor(coordinator, entry, desc, enabled=is_usb)
        if desc.key in USB_ONLY_KEYS
        else CaravanSensor(coordinator, entry, desc)
        for desc in SENSORS
    )


class CaravanSensor(SensorEntity):
    """Generic caravan sensor reading from the coordinator."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    entity_description: CaravanSensorDescription

    def __init__(
        self,
        coordinator: CaravanLocationCoordinator,
        entry: ConfigEntry,
        description: CaravanSensorDescription,
        enabled: bool = True,
    ) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_entity_registry_enabled_default = enabled
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Clever Caravan",
            manufacturer="Clever Caravan",
            model="Location",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self.entity_description.update_signal,
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.key == "heading":
            if (
                self.coordinator.latest is None
                or self.coordinator.latest.heading_deg is None
            ):
                return None
            return {"bearing_deg": round(self.coordinator.latest.heading_deg, 1)}
        if self.entity_description.key == "city":
            geo = self.coordinator.geocode
            if geo is None or geo.raw_address is None:
                return None
            addr = geo.raw_address
            # Build a human-readable single-line address from Nominatim parts.
            # Order: house_number road, suburb/city, state postcode, country
            parts = []
            road_bit = " ".join(
                p for p in (addr.get("house_number"), addr.get("road")) if p
            )
            if road_bit:
                parts.append(road_bit)
            if geo.city and geo.city != "Unknown":
                parts.append(geo.city)
            state_pc = " ".join(
                p for p in (geo.state, geo.postcode) if p
            )
            if state_pc:
                parts.append(state_pc)
            if geo.country:
                parts.append(geo.country)
            return {
                "full_address": ", ".join(parts) if parts else None,
                "raw_address": addr,
            }
        if self.entity_description.update_signal == SIGNAL_ABS_UPDATED:
            # Mandatory CC-BY 4.0 attribution for ABS Census data.
            attrs: dict = {
                "attribution": (
                    "Source: Australian Bureau of Statistics (ABS) "
                    "Census 2021, CC BY 4.0"
                ),
            }
            # Surface SAL code on the name sensor for joining with other
            # ABS datasets if the user wants to extend.
            if (
                self.entity_description.key == "statistical_area"
                and self.coordinator.abs_data is not None
            ):
                attrs["sal_code"] = self.coordinator.abs_data.sal_code
            return attrs
        if self.entity_description.update_signal == SIGNAL_WIKI_UPDATED:
            wiki = self.coordinator.wiki_data
            attrs = {"attribution": "Source: Wikipedia, CC BY-SA 4.0"}
            if wiki is not None:
                if wiki.title:
                    attrs["title"] = wiki.title
                if wiki.article_url:
                    attrs["article_url"] = wiki.article_url
                if wiki.extract:
                    # Full extract as attribute; state truncates to 255.
                    attrs["full_extract"] = wiki.extract
            return attrs
        if self.entity_description.update_signal == SIGNAL_METEOSTAT_UPDATED:
            return {
                "attribution": (
                    "Source: Meteostat, climate normals 1991-2020"
                ),
            }
        return None

    @property
    def available(self) -> bool:
        if self.entity_description.key == "status":
            return True
        if self.entity_description.update_signal == SIGNAL_GEOCODE_UPDATED:
            return self.coordinator.geocode is not None
        if self.entity_description.update_signal == SIGNAL_ABS_UPDATED:
            return self.coordinator.abs_data is not None
        if self.entity_description.update_signal == SIGNAL_WIKI_UPDATED:
            return self.coordinator.wiki_data is not None
        if self.entity_description.update_signal == SIGNAL_METEOSTAT_UPDATED:
            return self.coordinator.meteostat_data is not None
        return self.coordinator.latest is not None
