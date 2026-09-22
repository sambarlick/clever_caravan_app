# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Parser for Safety Sam (SYTPMS-family) BLE TPMS advertisements.

Payload layout (16 bytes inside manufacturer data, company ID 0x0100):

    offset  size  field
    0-5     6     sensor MAC echo (byte 0 = 0x80 + wheel index)
    6-9     4     pressure, uint32 little-endian, pascals
    10-13   4     temperature, int32 little-endian, °C x 100
    14      1     battery, percent
    15      1     alarm flag (non-zero = leak / fast deflation alarm)

Verified against live captures from Safety Sam sensors, June 2026.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from .const import MANUFACTURER_ID, MAX_WHEELS, WHEEL_BASE

PAYLOAD_LEN = 16


@dataclass(frozen=True)
class TPMSReading:
    """A decoded TPMS advertisement."""

    address: str
    wheel: int  # 1-based wheel position
    pressure_kpa: float
    temperature_c: float
    battery_pct: int
    alarm: bool
    rssi: int


def supported(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if this advertisement looks like a Safety Sam sensor."""
    data = service_info.manufacturer_data.get(MANUFACTURER_ID)
    if data is None or len(data) < PAYLOAD_LEN:
        return False
    wheel_byte = data[0]
    return WHEEL_BASE <= wheel_byte < WHEEL_BASE + MAX_WHEELS


def parse(service_info: BluetoothServiceInfoBleak) -> TPMSReading | None:
    """Parse an advertisement into a TPMSReading, or None if not ours."""
    if not supported(service_info):
        return None
    data = service_info.manufacturer_data[MANUFACTURER_ID]

    (pressure_pa,) = struct.unpack_from("<I", data, 6)
    (temp_centi,) = struct.unpack_from("<i", data, 10)

    return TPMSReading(
        address=service_info.address,
        wheel=data[0] - WHEEL_BASE + 1,
        pressure_kpa=round(pressure_pa / 1000, 1),
        temperature_c=round(temp_centi / 100, 1),
        battery_pct=data[14],
        alarm=bool(data[15]),
        rssi=service_info.rssi,
    )


def short_address(address: str) -> str:
    """Return the last two octets of a MAC for friendly names."""
    return address.replace(":", "")[-4:].upper()
