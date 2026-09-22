# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Coordinator: canonical state + action layer."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    ABS_MIN_INTERVAL_S,
    CLIMB_GRADIENT_THRESHOLD_MS,
    CLIMB_WINDOW_S,
    DOMAIN,
    DOP_TO_METRES,
    GEOCODE_MIN_DELTA_DEG,
    GEOCODE_MIN_INTERVAL_S,
    GRADIENT_CLIMBING,
    GRADIENT_DESCENDING,
    GRADIENT_LEVEL,
    PARKED_UP_AFTER_MINUTES,
    SET_LOCATION_MIN_DELTA_DEG,
    SIGNAL_ABS_UPDATED,
    SIGNAL_GEOCODE_UPDATED,
    SIGNAL_LOCATION_UPDATED,
    SIGNAL_METEOSTAT_UPDATED,
    SIGNAL_WIKI_UPDATED,
    SPEED_DRIVING_THRESHOLD,
    SPEED_NOT_DRIVING_THRESHOLD,
    STATUS_DRIVING,
    STATUS_NOT_DRIVING,
    STATUS_PARKED_UP,
    STATUS_UNKNOWN,
    TIMEZONE_MIN_DELTA_DEG,
)
from .abs import AbsResult, lookup_sal_data
from .meteostat import MeteostatResult, fetch_climate_normals
from .nominatim import GeocodeResult, reverse_geocode
from .sources import LocationFix, LocationSource
from .wikipedia import WikiResult, fetch_summary

_LOGGER = logging.getLogger(__name__)

class CaravanLocationCoordinator:
    def __init__(self, hass: HomeAssistant, source: LocationSource) -> None:
        self.hass = hass
        self.source = source

        self._latest: LocationFix | None = None
        self._status: str | None = STATUS_UNKNOWN
        self._previous_status: str | None = STATUS_UNKNOWN
        self._last_movement: datetime | None = None
        self._geocode: GeocodeResult | None = None

        self._elev_buffer: deque[tuple[datetime, float]] = deque()
        self._climb_ms: float | None = None

        self._snapshot_lat: float | None = None
        self._snapshot_lon: float | None = None
        self._snapshot_elevation: float | None = None
        self._snapshot_accuracy_h: float | None = None
        self._snapshot_accuracy_v: float | None = None

        self._cold_start_bootstrap_pending = True
        self._last_set_location: tuple[float, float] | None = None
        self._last_timezone: tuple[float, float] | None = None
        self._last_geocode_at: datetime | None = None
        self._last_geocode_pos: tuple[float, float] | None = None

        self._abs_data: AbsResult | None = None
        self._last_abs_sal: str | None = None
        self._last_abs_at: datetime | None = None

        self._wiki_data: WikiResult | None = None
        self._last_wiki_sal: str | None = None

        self._meteostat_data: MeteostatResult | None = None
        self._last_meteostat_sal: str | None = None
        self._last_meteostat_month: int | None = None

        source.subscribe(self._on_fix)

    @property
    def latest(self) -> LocationFix | None:
        return self._latest

    @property
    def status(self) -> str | None:
        return self._status

    @property
    def display_latitude(self) -> float | None:
        if self._status == STATUS_DRIVING:
            return self._latest.latitude if self._latest else None
        return self._snapshot_lat

    @property
    def display_longitude(self) -> float | None:
        if self._status == STATUS_DRIVING:
            return self._latest.longitude if self._latest else None
        return self._snapshot_lon

    @property
    def display_elevation(self) -> float | None:
        if self._status == STATUS_DRIVING:
            return self._latest.elevation if self._latest else None
        return self._snapshot_elevation

    @property
    def display_accuracy_h(self) -> float | None:
        if self._status == STATUS_DRIVING:
            if self._latest and self._latest.hdop is not None:
                return round(self._latest.hdop * DOP_TO_METRES, 1)
            return None
        return self._snapshot_accuracy_h

    @property
    def display_accuracy_v(self) -> float | None:
        if self._status == STATUS_DRIVING:
            if self._latest and self._latest.vdop is not None:
                return round(self._latest.vdop * DOP_TO_METRES, 1)
            return None
        return self._snapshot_accuracy_v

    @property
    def display_speed(self) -> float | None:
        if self._status == STATUS_DRIVING:
            return self._latest.speed_kmh if self._latest else None
        return 0.0

    @property
    def display_climb_ms(self) -> float | None:
        # Dejitter climb rate: 0.0 when stationary
        if self._status == STATUS_DRIVING:
            return self._climb_ms
        return 0.0

    @property
    def gradient(self) -> str | None:
        climb = self.display_climb_ms
        if climb is None:
            return None
        if climb > CLIMB_GRADIENT_THRESHOLD_MS:
            return GRADIENT_CLIMBING
        if climb < -CLIMB_GRADIENT_THRESHOLD_MS:
            return GRADIENT_DESCENDING
        return GRADIENT_LEVEL

    @property
    def is_healthy(self) -> bool:
        if self._latest is None:
            return False
        age = (dt_util.utcnow() - self._latest.timestamp).total_seconds()
        return self._latest.valid and age < 600

    @property
    def geocode(self) -> GeocodeResult | None:
        return self._geocode

    @property
    def abs_data(self) -> AbsResult | None:
        return self._abs_data

    @property
    def wiki_data(self) -> WikiResult | None:
        return self._wiki_data

    @property
    def meteostat_data(self) -> MeteostatResult | None:
        return self._meteostat_data

    @callback
    def _on_fix(self, fix: LocationFix) -> None:
        # Parked Up gate: drop fixes that are within snapshot tolerance
        # so the database, zone.home, and downstream automations don't
        # churn on every sub-metre GPS jitter from chatty sources like
        # Starlink. Genuine movement (drives off, gets towed) clears
        # the gate and resumes normal processing.
        if (
            self._status == STATUS_PARKED_UP
            and fix.valid
            and self._snapshot_lat is not None
            and self._snapshot_lon is not None
            and abs(fix.latitude - self._snapshot_lat) < SET_LOCATION_MIN_DELTA_DEG
            and abs(fix.longitude - self._snapshot_lon) < SET_LOCATION_MIN_DELTA_DEG
        ):
            return
        self._latest = fix
        self._update_status(fix)
        self._update_climb(fix)
        self._update_snapshot(fix)
        async_dispatcher_send(self.hass, SIGNAL_LOCATION_UPDATED)

        # Capture before _should_run_actions() consumes the flag.
        is_bootstrap = self._cold_start_bootstrap_pending

        if fix.valid and self._should_run_actions():
            entered_parked = (
                self._status == STATUS_PARKED_UP
                and self._previous_status != STATUS_PARKED_UP
            )
            # Enrich on park transition, or on the first valid fix after
            # startup (HA restarted while stationary). If the rig boots
            # mid-drive, skip — the park transition will cover it.
            enrich = entered_parked or (
                is_bootstrap and self._status != STATUS_DRIVING
            )
            self.hass.async_create_task(self._run_actions(fix, enrich))

        self._previous_status = self._status

    def _should_run_actions(self) -> bool:
        if self._cold_start_bootstrap_pending:
            self._cold_start_bootstrap_pending = False
            return True
        if self._status == STATUS_DRIVING:
            return True
        if self._previous_status == STATUS_DRIVING and self._status != STATUS_DRIVING:
            return True
        if self._status == STATUS_PARKED_UP and self._previous_status != STATUS_PARKED_UP:
            return True
        return False

    async def _run_actions(self, fix: LocationFix, enrich: bool) -> None:
        # Geocode-trigger path: zone.home + timezone need to track during
        # drive (state lines, time zones), so they keep firing on movement.
        # Geocode itself also runs here so the city/state are fresh.
        await self._update_zone_home(fix)
        await self._update_timezone(fix)
        await self._update_geocode(fix)

        # Enrichment path: ABS, Wikipedia, Meteostat. Runs on the Parked Up
        # transition and on the cold-start bootstrap. The decision is made
        # synchronously in _on_fix and passed in; re-reading
        # self._previous_status here is unsafe because it is reassigned
        # before this deferred task runs.
        if enrich:
            await self._update_abs(fix)
            await self._update_wiki()
            await self._update_meteostat(fix)

    async def async_force_update(self) -> None:
        """Force-run all action layers against the latest fix.

        Bypasses all throttling: minimum intervals, distance deltas, and
        SAL cache. Called by the clever_caravan_location.update service.
        """
        if self._latest is None or not self._latest.valid:
            _LOGGER.warning(
                "Force update requested but no valid fix available yet"
            )
            return
        fix = self._latest
        await self._update_zone_home(fix, force=True)
        await self._update_timezone(fix, force=True)
        await self._update_geocode(fix, force=True)
        await self._update_abs(fix, force=True)
        await self._update_wiki(force=True)
        await self._update_meteostat(fix, force=True)

    def _update_status(self, fix: LocationFix) -> None:
        if not fix.valid:
            self._status = STATUS_UNKNOWN
            return

        speed = fix.speed_kmh
        now = fix.timestamp

        if speed is None:
            self._status = STATUS_NOT_DRIVING
            return

        if speed >= SPEED_DRIVING_THRESHOLD:
            self._status = STATUS_DRIVING
            self._last_movement = now
            return

        if speed >= SPEED_NOT_DRIVING_THRESHOLD:
            self._status = STATUS_NOT_DRIVING
            return

        if self._last_movement is None:
            self._last_movement = now
            self._status = STATUS_NOT_DRIVING
            return

        dwell = now - self._last_movement
        if dwell >= timedelta(minutes=PARKED_UP_AFTER_MINUTES):
            self._status = STATUS_PARKED_UP
        else:
            self._status = STATUS_NOT_DRIVING

    def _update_snapshot(self, fix: LocationFix) -> None:
        if not fix.valid:
            return
        if self._status == STATUS_DRIVING or self._snapshot_lat is None:
            self._snapshot_lat = fix.latitude
            self._snapshot_lon = fix.longitude
            self._snapshot_elevation = fix.elevation
            if fix.hdop is not None:
                self._snapshot_accuracy_h = round(fix.hdop * DOP_TO_METRES, 1)
            if fix.vdop is not None:
                self._snapshot_accuracy_v = round(fix.vdop * DOP_TO_METRES, 1)

    def _update_climb(self, fix: LocationFix) -> None:
        if not fix.valid or fix.elevation is None:
            return
        now = fix.timestamp
        self._elev_buffer.append((now, fix.elevation))
        cutoff = now - timedelta(seconds=CLIMB_WINDOW_S)
        while self._elev_buffer and self._elev_buffer[0][0] < cutoff:
            self._elev_buffer.popleft()
        if len(self._elev_buffer) < 2:
            self._climb_ms = None
            return
        oldest_t, oldest_e = self._elev_buffer[0]
        dt = (now - oldest_t).total_seconds()
        if dt <= 0:
            return
        self._climb_ms = (fix.elevation - oldest_e) / dt

    async def _update_zone_home(self, fix: LocationFix, force: bool = False) -> None:
        if not force and not self._delta_exceeds(self._last_set_location, fix, SET_LOCATION_MIN_DELTA_DEG):
            return
        try:
            await self.hass.services.async_call(
                "homeassistant", "set_location",
                {
                    "latitude": fix.latitude,
                    "longitude": fix.longitude,
                    **({"elevation": int(fix.elevation)} if fix.elevation is not None else {}),
                },
                blocking=False,
            )
            self._last_set_location = (fix.latitude, fix.longitude)
        except Exception:
            pass

    async def _update_timezone(self, fix: LocationFix, force: bool = False) -> None:
        if not force and not self._delta_exceeds(self._last_timezone, fix, TIMEZONE_MIN_DELTA_DEG):
            return
        try:
            from tzfpy import get_tz
            tz_name = await self.hass.async_add_executor_job(get_tz, fix.longitude, fix.latitude)
            if tz_name and tz_name != self.hass.config.time_zone:
                await self.hass.config.async_set_time_zone(tz_name)
            self._last_timezone = (fix.latitude, fix.longitude)
        except Exception:
            pass

    async def _update_geocode(self, fix: LocationFix, force: bool = False) -> None:
        now = dt_util.utcnow()
        if not force:
            time_ok = (self._last_geocode_at is None or (now - self._last_geocode_at).total_seconds() >= GEOCODE_MIN_INTERVAL_S)
            dist_ok = self._delta_exceeds(self._last_geocode_pos, fix, GEOCODE_MIN_DELTA_DEG)
            if not (time_ok and dist_ok):
                return
        session = async_get_clientsession(self.hass)
        result = await reverse_geocode(session, fix.latitude, fix.longitude)
        self._last_geocode_at = now
        self._last_geocode_pos = (fix.latitude, fix.longitude)
        if result is not None:
            self._geocode = result
            async_dispatcher_send(self.hass, SIGNAL_GEOCODE_UPDATED)

    async def _update_abs(self, fix: LocationFix, force: bool = False) -> None:
        # Gate on Australia — ABS only covers AU.
        # Outside AU, retain last-known values silently.
        if self._geocode is None or self._geocode.country_code != "au":
            return

        now = dt_util.utcnow()
        if not force:
            # Throttle to ABS_MIN_INTERVAL_S between calls.
            if (
                self._last_abs_at is not None
                and (now - self._last_abs_at).total_seconds() < ABS_MIN_INTERVAL_S
            ):
                return

        session = async_get_clientsession(self.hass)
        result = await lookup_sal_data(session, fix.latitude, fix.longitude)
        self._last_abs_at = now

        if result is None or result.sal_code is None:
            # Network/lookup failure or point outside SAL coverage.
            # Retain previous data; do not null sensors.
            return

        # Cache by SAL code: skip dispatch if we're still in the same suburb/locality.
        if result.sal_code == self._last_abs_sal and self._abs_data is not None:
            return

        self._abs_data = result
        self._last_abs_sal = result.sal_code
        async_dispatcher_send(self.hass, SIGNAL_ABS_UPDATED)

    async def _update_wiki(self, force: bool = False) -> None:
        """Fetch Wikipedia summary keyed off current city/state.

        Cache key: SAL code (so we only refetch when crossing into a
        new locality). When forced, bypass the cache.
        """
        if self._geocode is None or self._geocode.country_code != "au":
            return
        if self._abs_data is None:
            return  # need SAL code for cache; rare race, skip and let next trigger handle it

        sal_code = self._abs_data.sal_code
        if not force and sal_code == self._last_wiki_sal and self._wiki_data is not None:
            return

        city = self._geocode.city
        state = self._geocode.state
        if not city:
            return

        session = async_get_clientsession(self.hass)
        result = await fetch_summary(session, city, state)
        if result is None:
            # Retain previous; don't null
            return

        self._wiki_data = result
        self._last_wiki_sal = sal_code
        async_dispatcher_send(self.hass, SIGNAL_WIKI_UPDATED)

    async def _update_meteostat(self, fix: LocationFix, force: bool = False) -> None:
        """Fetch Meteostat climate normals.

        Cache key: SAL code AND current calendar month. Refetches
        on month rollover (so May normals get replaced by June
        normals on the 1st of June even if the user hasn't moved).
        """
        if self._geocode is None or self._geocode.country_code != "au":
            return
        if self._abs_data is None:
            return

        sal_code = self._abs_data.sal_code
        current_month = dt_util.utcnow().month
        if (
            not force
            and sal_code == self._last_meteostat_sal
            and current_month == self._last_meteostat_month
            and self._meteostat_data is not None
        ):
            return

        session = async_get_clientsession(self.hass)
        result = await fetch_climate_normals(
            session, fix.latitude, fix.longitude, fix.elevation
        )
        if result is None:
            return

        self._meteostat_data = result
        self._last_meteostat_sal = sal_code
        self._last_meteostat_month = current_month
        async_dispatcher_send(self.hass, SIGNAL_METEOSTAT_UPDATED)

    @staticmethod
    def _delta_exceeds(last: tuple[float, float] | None, fix: LocationFix, threshold_deg: float) -> bool:
        if last is None:
            return True
        return (abs(fix.latitude - last[0]) >= threshold_deg or abs(fix.longitude - last[1]) >= threshold_deg)

def get_coordinator(hass: HomeAssistant, entry_id: str) -> CaravanLocationCoordinator:
    return hass.data[DOMAIN][entry_id]["coordinator"]
