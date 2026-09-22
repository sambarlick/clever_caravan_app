# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Base class for location sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Callable

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocationFix:
    """Normalised location fix from any source.

    Core fields are required. GPS-specific fields default to None so
    sources that don't have them (entity, manual) leave them off.
    """

    latitude: float
    longitude: float
    elevation: float | None
    speed_kmh: float | None
    timestamp: datetime
    valid: bool
    # Optional GPS-specific signal — populated by USB source primarily
    fix_quality: int | None = None       # 0..9 per NMEA $GPGGA
    fix_mode: int | None = None          # 1=no fix, 2=2D, 3=3D ($GPGSA)
    satellites_used: int | None = None
    satellites_visible: int | None = None
    hdop: float | None = None
    vdop: float | None = None
    heading_deg: float | None = None     # course over ground, degrees
    gps_time: datetime | None = None     # GPS-reported UTC timestamp


class LocationSource(ABC):
    """Adapter contract."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        self.hass = hass
        self.config = config
        self._listener: Callable[[LocationFix], None] | None = None
        self._unsub: Callable[[], None] | None = None
        self._latest: LocationFix | None = None

    @property
    def latest(self) -> LocationFix | None:
        return self._latest

    def subscribe(self, listener: Callable[[LocationFix], None]) -> None:
        self._listener = listener

    @abstractmethod
    async def async_start(self) -> None:
        """Begin listening to the underlying source."""

    async def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    def _publish(self, fix: LocationFix) -> None:
        self._latest = fix
        if self._listener is not None:
            # Bridge to the event loop. Sources may publish from sync
            # threads (USB executor, state-change callbacks via certain
            # paths), but the listener calls async_dispatcher_send which
            # is event-loop-only. hass.add_job handles both cases:
            # already on-loop → schedules, on a thread → bridges.
            self.hass.add_job(self._listener, fix)
