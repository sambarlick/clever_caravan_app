# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Victron BLE Instant Readout -> Venus (service, instance, path) mapping.

HA-free so it unit-tests standalone. Turns a decrypted victron-ble record into
the SAME (service, instance, path, value) tuples that VenusHub emits over MQTT,
so the existing entities in const.py light up from BLE with no entity changes.

Setup-agnostic: the device type is auto-detected from each advertisement and
mirrored onto its matching Venus service. Nothing about any particular rig is
hardcoded; the only per-device input is the (instance, key) supplied by config.

  MPPT solar charger  -> solarcharger/<instance>/*
  SmartShunt / BMV    -> battery/<instance>/*  AND  system/0/Dc/Battery/*
  Orion XS DC-DC      -> dcdc/<instance>/*

Parsing/decryption/scaling come from the official `victron-ble` library
(detect_device_type + Device.parse). This module only drives the library and
maps its typed getters onto Venus dbus paths, so only the mapping needs testing.

The BLE-side constants (company id, options key) live here rather than in
const.py so that const.py — which holds the large MQTT entity tables — does not
have to be touched to add the BLE feature.
"""
from __future__ import annotations

from collections.abc import Callable

try:
    from victron_ble.devices import detect_device_type
    from victron_ble.exceptions import AdvertisementKeyMismatchError

    _HAVE_LIB = True
except ImportError:  # let the mapper be imported/tested without the dependency
    detect_device_type = None  # type: ignore[assignment]

    class AdvertisementKeyMismatchError(Exception):  # type: ignore[no-redef]
        pass

    _HAVE_LIB = False

# --------------------------------------------------------------------------- #
# BLE constants (shared by ble_hub, config_flow, repairs, __init__)
# --------------------------------------------------------------------------- #
VICTRON_COMPANY_ID = 0x02E1  # 737 — Victron Energy manufacturer id
CONF_BLE_DEVICES = "ble_devices"  # entry.options list of {address,key,kind,instance}
CONF_BLE_IGNORED = "ble_ignored"  # entry.options list of MACs to never nag about
# Installer switch: raise Repairs for un-keyed Victron adverts. Off once the
# rig's own devices are added, so passing/neighbouring caravans never nag.
CONF_BLE_DISCOVERY = "ble_discovery"
ISSUE_PREFIX = "ble_unkeyed_"


def discovery_enabled(options) -> bool:
    """Explicit option wins; legacy entries default ON only if nothing is keyed yet."""
    if CONF_BLE_DISCOVERY in options:
        return bool(options[CONF_BLE_DISCOVERY])
    return not options.get(CONF_BLE_DEVICES)

# Victron advertisement keys are 16 bytes = 32 hex characters, always.
KEY_LEN_HEX = 32

# Venus service names (see const.py).
SC_SERVICE = "solarcharger"
BATT_SERVICE = "battery"
DCDC_SERVICE = "dcdc"
SYSTEM_SERVICE = "system"
SYSTEM_INSTANCE = "0"  # Venus system service is always instance 0

# victron-ble Device class name -> internal record kind.
_KIND_BY_DEVICE = {
    "SolarCharger": "solar_charger",
    "BatteryMonitor": "battery_monitor",
    "OrionXS": "orion_xs",
}

# Human labels for the config UI / repairs prompts.
KIND_LABELS = {
    "solar_charger": "Solar Charger (MPPT)",
    "battery_monitor": "Battery Monitor (SmartShunt/BMV)",
    "orion_xs": "Orion XS DC-DC",
}

Triple = tuple[str, str, str, object]  # (service, instance, path, value)


def is_valid_key(key: str) -> bool:
    """A Victron advertisement key is exactly 32 hex characters (16 bytes)."""
    k = (key or "").strip()
    if len(k) != KEY_LEN_HEX:
        return False
    try:
        bytes.fromhex(k)
    except ValueError:
        return False
    return True


def status_triple(cfg: dict) -> tuple[str, str, str]:
    """The per-device triple whose BLE freshness means 'this device is decoding'.

    Uses a datapoint unique to the device's own instance (not the shared
    system/0 tiles), so one device's status can't be confused with another's.
    """
    kind = cfg.get("kind")
    inst = str(cfg.get("instance"))
    if kind == "solar_charger":
        return (SC_SERVICE, inst, "Dc/0/Voltage")
    if kind == "battery_monitor":
        return (BATT_SERVICE, inst, "Dc/0/Voltage")
    if kind == "orion_xs":
        return (DCDC_SERVICE, inst, "Dc/0/Voltage")
    return (SYSTEM_SERVICE, SYSTEM_INSTANCE, "Dc/Battery/Voltage")



def detect_kind(raw: bytes) -> str | None:
    """Return the record kind for a Victron advert, or None.

    Reads only the unencrypted header (model id + mode), so NO key is needed —
    this is what lets the config flow and repairs show the device type before a
    key has been entered.
    """
    if not _HAVE_LIB:
        return None
    # detect_device_type unpacks bytes 2-5 without guarding the length, so a
    # short "GATT/continuation" advert (only a byte or two of manufacturer data)
    # makes it raise struct.error. Treat any unparseable buffer as "not ours".
    try:
        cls = detect_device_type(raw)
    except Exception:  # noqa: BLE001 - short/garbage advert, not a Victron IR frame
        return None
    if cls is None:
        return None
    return _KIND_BY_DEVICE.get(cls.__name__)


def resolve_instance(hub, kind: str, existing: list[dict]) -> str:
    """Pick the Venus instance a newly-keyed BLE device should mirror.

    Uses the live MQTT instances when available so BLE folds onto the SAME
    entities the Cerbo created. Solar chargers are auto-assigned across the live
    solarcharger instances (any free one — the Total is always right, only a
    per-charger label might differ). Falls back to a synthetic instance when
    MQTT isn't up (e.g. a Cerbo-less rig). `existing` is the already-configured
    BLE device list, so two devices never claim the same instance.

    `hub` is the VenusHub (duck-typed: needs .instances_of(service)); may be None.
    """
    taken = {d["instance"] for d in existing if d.get("kind") == kind}

    if kind == "battery_monitor":
        live = sorted(hub.instances_of(BATT_SERVICE)) if hub else []
        return live[0] if live else "277"

    if kind == "solar_charger":
        live = sorted(hub.instances_of(SC_SERVICE)) if hub else []
        for inst in live:
            if inst not in taken:
                return inst
        n = 288
        while str(n) in taken:
            n += 1
        return str(n)

    if kind == "orion_xs":
        live = sorted(hub.instances_of(DCDC_SERVICE)) if hub else []
        for inst in live:
            if inst not in taken:
                return inst
        n = 0
        while str(n) in taken:
            n += 1
        return str(n)

    return "0"


def map_solar_charger(d, instance: str) -> list[Triple]:
    """MPPT record -> solarcharger/<instance>/* triples."""
    out: list[Triple] = []
    v = d.get_battery_voltage()           # V
    if v is not None:
        out.append((SC_SERVICE, instance, "Dc/0/Voltage", v))
    c = d.get_battery_charging_current()  # A
    if c is not None:
        out.append((SC_SERVICE, instance, "Dc/0/Current", c))
    state = d.get_charge_state()          # OperationMode enum
    if state is not None:
        out.append((SC_SERVICE, instance, "State", state.value))
    p = d.get_solar_power()               # W (also feeds the Total Solar aggregate)
    if p is not None:
        out.append((SC_SERVICE, instance, "Yield/Power", p))
    y = d.get_yield_today()               # Wh from the library
    if y is not None:
        # const's History/Daily/0/Yield entity is kWh -> convert.
        out.append((SC_SERVICE, instance, "History/Daily/0/Yield", round(y / 1000, 3)))
    return out


def map_battery_monitor(d, instance: str) -> list[Triple]:
    """SmartShunt/BMV record -> system/0/Dc/Battery/* (headline) + battery/<inst>/*."""
    out: list[Triple] = []
    v = d.get_voltage()           # V
    c = d.get_current()           # A
    soc = d.get_soc()             # %
    ttg = d.get_remaining_mins()  # MINUTES from the library
    ah = d.get_consumed_ah()      # Ah (already negative)

    # --- the configured monitor drives the system battery tiles ---
    if v is not None:
        out.append((SYSTEM_SERVICE, SYSTEM_INSTANCE, "Dc/Battery/Voltage", v))
    if c is not None:
        out.append((SYSTEM_SERVICE, SYSTEM_INSTANCE, "Dc/Battery/Current", c))
    if v is not None and c is not None:
        out.append((SYSTEM_SERVICE, SYSTEM_INSTANCE, "Dc/Battery/Power", round(v * c, 1)))
    if soc is not None:
        out.append((SYSTEM_SERVICE, SYSTEM_INSTANCE, "Dc/Battery/Soc", soc))
    if ttg is not None:
        # const's _ttg_text transform expects SECONDS; the library gives minutes.
        out.append((SYSTEM_SERVICE, SYSTEM_INSTANCE, "Dc/Battery/TimeToGo", ttg * 60))

    # --- the battery-service diagnostics (bm_* entities, disabled by default) ---
    if v is not None:
        out.append((BATT_SERVICE, instance, "Dc/0/Voltage", v))
    if c is not None:
        out.append((BATT_SERVICE, instance, "Dc/0/Current", c))
    if ah is not None:
        out.append((BATT_SERVICE, instance, "ConsumedAmphours", ah))
    return out


def map_orion_xs(d, instance: str) -> list[Triple]:
    """Orion XS DC-DC record -> dcdc/<instance>/* triples."""
    out: list[Triple] = []
    state = d.get_charge_state()   # OperationMode enum
    if state is not None:
        out.append((DCDC_SERVICE, instance, "State", state.value))
    ov = d.get_output_voltage()    # V
    oc = d.get_output_current()    # A
    iv = d.get_input_voltage()     # V
    ic = d.get_input_current()     # A
    if ov is not None:
        out.append((DCDC_SERVICE, instance, "Dc/0/Voltage", ov))
    if oc is not None:
        out.append((DCDC_SERVICE, instance, "Dc/0/Current", oc))
    if ov is not None and oc is not None:
        out.append((DCDC_SERVICE, instance, "Dc/0/Power", round(ov * oc, 1)))
    if iv is not None:
        out.append((DCDC_SERVICE, instance, "Dc/In/V", iv))
    if ic is not None:
        out.append((DCDC_SERVICE, instance, "Dc/In/I", ic))
    return out


_MAPPERS: dict[str, Callable[[object, str], list[Triple]]] = {
    "solar_charger": map_solar_charger,
    "battery_monitor": map_battery_monitor,
    "orion_xs": map_orion_xs,
}


def parse_and_map(raw: bytes, key: str, instance: str) -> list[Triple]:
    """Decrypt+parse a Victron extra-manufacturer-data blob (company 0x02E1)
    and map it to Venus triples.

    Returns [] for an unsupported device type or a wrong key (never raises for
    those cases — a bad key just yields no data, so one mis-keyed device can't
    take the whole feed down).
    """
    if not _HAVE_LIB:
        raise RuntimeError("victron-ble is not installed")
    try:
        cls = detect_device_type(raw)
    except Exception:  # noqa: BLE001 - short/garbage advert, not a Victron IR frame
        return []
    if cls is None:
        return []
    kind = _KIND_BY_DEVICE.get(cls.__name__)
    if kind is None:
        return []  # a Victron device we don't map (inverter, vebus, ac charger, ...)
    try:
        data = cls(key).parse(raw)
    except AdvertisementKeyMismatchError:
        return []
    except Exception:  # noqa: BLE001 - truncated/garbage payload; drop this advert
        return []
    return _MAPPERS[kind](data, instance)
