"""Config flow for Clever Caravan Weather.

One-click install: no questions asked. Reads location from zone.home,
validates against BOM, then creates the entry with all sensors enabled
under the "Caravan" basename. Designed to be reinstalled rather than
reconfigured — no options flow is exposed.
"""
import logging

from homeassistant import config_entries, exceptions
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FORECASTS_BASENAME,
    CONF_FORECASTS_CREATE,
    CONF_FORECASTS_DAYS,
    CONF_FORECASTS_MONITORED,
    CONF_OBSERVATIONS_BASENAME,
    CONF_OBSERVATIONS_CREATE,
    CONF_OBSERVATIONS_MONITORED,
    CONF_WARNINGS_BASENAME,
    CONF_WARNINGS_CREATE,
    CONF_WEATHER_NAME,
    DOMAIN,
    OBSERVATION_SENSOR_TYPES,
    FORECAST_SENSOR_TYPES,
)
from .PyBoM.collector import Collector

_LOGGER = logging.getLogger(__name__)

# Default basename used for every naming field. Picking one consistent value
# means entities all sit under the same prefix: weather.caravan,
# sensor.caravan_temp_now, sensor.caravan_warnings, etc.
DEFAULT_BASENAME = "Caravan"

# BOM serves up to 7 days of daily forecasts.
DEFAULT_FORECAST_DAYS = 7


def _get_home_zone_coords(hass: HomeAssistant):
    """Get the current latitude/longitude from zone.home with HA core fallback."""
    home_zone = hass.states.get("zone.home")
    if home_zone is not None:
        lat = home_zone.attributes.get("latitude")
        lon = home_zone.attributes.get("longitude")
        if lat is not None and lon is not None:
            return lat, lon
    _LOGGER.warning(
        "Clever Caravan Weather: zone.home not available, falling back to HA core location"
    )
    return hass.config.latitude, hass.config.longitude


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """One-click config flow for Clever Caravan Weather."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Single-step install — no questions, sensible defaults."""
        # Only one install per HA instance — there is only one zone.home.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors = {}
        try:
            lat, lon = _get_home_zone_coords(self.hass)

            collector = Collector(lat, lon, hass=self.hass)
            await collector.get_locations_data()

            if collector.locations_data is None:
                _LOGGER.debug(
                    "Unsupported location from zone.home: %s, %s", lat, lon
                )
                errors["base"] = "bad_location"
                return self.async_show_form(step_id="user", errors=errors)

            # Build defaults: every category enabled, every sensor monitored.
            data = {
                CONF_LATITUDE: lat,
                CONF_LONGITUDE: lon,
                CONF_WEATHER_NAME: DEFAULT_BASENAME,
                CONF_OBSERVATIONS_CREATE: True,
                CONF_OBSERVATIONS_BASENAME: DEFAULT_BASENAME,
                CONF_OBSERVATIONS_MONITORED: [
                    "temp",
                    "humidity",
                    "wind_speed_kilometre",
                    "wind_direction",
                    "gust_speed_kilometre",
                    "dew_point",
                ],
                CONF_FORECASTS_CREATE: True,
                CONF_FORECASTS_BASENAME: DEFAULT_BASENAME,
                CONF_FORECASTS_MONITORED: ["short_text", "uv_category", "uv_max_index", "fire_danger"],
                CONF_FORECASTS_DAYS: DEFAULT_FORECAST_DAYS,
                CONF_WARNINGS_CREATE: True,
                CONF_WARNINGS_BASENAME: DEFAULT_BASENAME,
            }

            # Mirror data into options. The existing __init__.py unload logic
            # reads from entry.options to decide which entities to keep, and
            # since we have no options flow to populate it later, we seed it
            # at install time.
            return self.async_create_entry(
                title="Clever Caravan Weather",
                data=data,
                options=dict(data),
            )

        except Exception:
            _LOGGER.exception("Unexpected exception during install")
            errors["base"] = "unknown"

        return self.async_show_form(step_id="user", errors=errors)


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""
