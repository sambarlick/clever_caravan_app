# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Config flow for Clever Caravan: Power."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .ble_map import (
    CONF_BLE_DEVICES,
    CONF_BLE_DISCOVERY,
    CONF_BLE_IGNORED,
    KIND_LABELS,
    VICTRON_COMPANY_ID,
    detect_kind,
    discovery_enabled,
    is_valid_key,
    resolve_instance,
)
from .const import (
    CONF_CURRENT_LIMIT_MAX,
    CONF_CURRENT_LIMIT_MIN,
    CONF_FLOW_DEADBAND,
    CONF_INSTANCE_NAME,
    CONF_PORTAL_ID,
    CONF_RELAY_NAME,
    CONF_SSH_KEY,
    CONF_USE_SSL,
    DEFAULT_CURRENT_LIMIT_MAX,
    DEFAULT_CURRENT_LIMIT_MIN,
    DEFAULT_FLOW_DEADBAND,
    DEFAULT_HOST,
    DEFAULT_SSH_KEY,
    DEFAULT_PORT,
    DOMAIN,
    NAMEABLE_SERVICES,
)
from .hub import VenusHub

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_USERNAME, default=""): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
        vol.Optional(CONF_USE_SSL, default=False): bool,
    }
)


def _probe(user_input: dict[str, Any]) -> str | None:
    """Connect briefly and return the detected portal ID (runs in executor)."""
    hub = VenusHub(
        host=user_input[CONF_HOST],
        port=user_input[CONF_PORT],
        username=user_input.get(CONF_USERNAME) or None,
        password=user_input.get(CONF_PASSWORD) or None,
        use_ssl=user_input.get(CONF_USE_SSL, False),
    )
    try:
        hub.start()
        return hub.wait_for_portal(12.0)
    finally:
        hub.stop()


RELAY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_RELAY_NAME.format(0), default="Relay 1"): str,
        vol.Required(CONF_RELAY_NAME.format(1), default="Relay 2"): str,
    }
)


class CcpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                portal_id = await self.hass.async_add_executor_job(_probe, user_input)
            except OSError:
                portal_id = None
                errors["base"] = "cannot_connect"
            if portal_id:
                await self.async_set_unique_id(portal_id)
                self._abort_if_unique_id_configured()
                user_input[CONF_PORTAL_ID] = portal_id
                self._data = user_input
                return await self.async_step_relays()
            errors.setdefault("base", "no_portal")

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Change connection details (e.g. the Cerbo's IP) for an existing entry."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                portal_id = await self.hass.async_add_executor_job(_probe, user_input)
            except OSError:
                portal_id = None
                errors["base"] = "cannot_connect"
            if portal_id:
                if entry.unique_id and portal_id != entry.unique_id:
                    errors["base"] = "different_device"
                else:
                    new_data = {**entry.data, **user_input, CONF_PORTAL_ID: portal_id}
                    self.hass.config_entries.async_update_entry(entry, data=new_data)
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reconfigure_successful")
            errors.setdefault("base", "no_portal")

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, DEFAULT_HOST)): str,
                vol.Required(CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Optional(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")): str,
                vol.Optional(CONF_PASSWORD, default=entry.data.get(CONF_PASSWORD, "")): str,
                vol.Optional(CONF_USE_SSL, default=entry.data.get(CONF_USE_SSL, False)): bool,
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    async def async_step_relays(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Name the Cerbo's two relays (e.g. Internal Fan / External Fan)."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Cerbo GX ({self._data[CONF_PORTAL_ID]})",
                data=self._data,
                options=user_input,
            )
        return self.async_show_form(step_id="relays", data_schema=RELAY_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CcpOptionsFlow()


class CcpOptionsFlow(config_entries.OptionsFlow):
    """Per-install tuning and Victron BLE fallback key management."""

    # ---------------------------------------------------------------- menu
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["tuning", "ble"])

    # ------------------------------------------------------------- tuning
    def _instance_name_fields(self, options: dict) -> dict:
        """Build a name field for each instance of a nameable service that has
        MORE THAN ONE instance discovered. Single-instance services are skipped
        (their entities drop the number automatically). Returns {} if the hub
        isn't reachable yet or nothing qualifies.
        """
        fields: dict = {}
        data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if data is None:
            return fields
        hub = data.hub
        for service in NAMEABLE_SERVICES:
            instances = sorted(hub.instances_of(service))
            if len(instances) <= 1:
                continue  # single instance -> no field, number is dropped
            for instance in instances:
                key = CONF_INSTANCE_NAME.format(service=service, instance=instance)
                default = options.get(key, "")
                fields[vol.Optional(key, default=default)] = str
        return fields

    async def async_step_tuning(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            # Preserve options not shown here (notably the BLE device list).
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )

        options = self.config_entry.options
        schema_dict = {
            vol.Required(
                CONF_RELAY_NAME.format(0),
                default=options.get(CONF_RELAY_NAME.format(0), "Relay 1"),
            ): str,
            vol.Required(
                CONF_RELAY_NAME.format(1),
                default=options.get(CONF_RELAY_NAME.format(1), "Relay 2"),
            ): str,
            vol.Required(
                CONF_CURRENT_LIMIT_MIN,
                default=options.get(CONF_CURRENT_LIMIT_MIN, DEFAULT_CURRENT_LIMIT_MIN),
            ): vol.Coerce(float),
            vol.Required(
                CONF_CURRENT_LIMIT_MAX,
                default=options.get(CONF_CURRENT_LIMIT_MAX, DEFAULT_CURRENT_LIMIT_MAX),
            ): vol.Coerce(float),
            vol.Required(
                CONF_FLOW_DEADBAND,
                default=options.get(CONF_FLOW_DEADBAND, DEFAULT_FLOW_DEADBAND),
            ): vol.Coerce(float),
            vol.Required(
                CONF_SSH_KEY,
                default=options.get(CONF_SSH_KEY, DEFAULT_SSH_KEY),
            ): str,
        }
        # Append dynamic per-instance name fields (only for services with >1).
        schema_dict.update(self._instance_name_fields(options))
        return self.async_show_form(step_id="tuning", data_schema=vol.Schema(schema_dict))

    # --------------------------------------------------------------- BLE
    def _discovered_unkeyed(
        self, configured_macs: set[str], ignored_macs: set[str]
    ) -> list[tuple[str, str]]:
        """(mac, kind) for currently-advertising Victron devices with no key
        that haven't been ignored."""
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=False):
            mac = info.address.upper()
            if mac in configured_macs or mac in ignored_macs or mac in seen:
                continue
            raw = info.manufacturer_data.get(VICTRON_COMPANY_ID)
            if not raw:
                continue
            kind = detect_kind(raw)
            if kind is None:
                continue
            seen.add(mac)
            out.append((mac, kind))
        return out

    async def async_step_ble(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        options = self.config_entry.options
        configured = list(options.get(CONF_BLE_DEVICES, []))
        configured_macs = {d["address"].upper() for d in configured}
        ignored = [m.upper() for m in options.get(CONF_BLE_IGNORED, [])]
        discovered = self._discovered_unkeyed(configured_macs, set(ignored))

        data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        hub = data.hub if data else None

        if user_input is not None:
            errors: dict[str, str] = {}
            pending: list[tuple[str, str, str]] = []
            for mac, kind in discovered:
                key = (user_input.get(f"key_{mac}") or "").strip()
                if not key:
                    continue
                if not is_valid_key(key):
                    errors["base"] = "invalid_key"
                    continue
                pending.append((mac, kind, key))

            if not errors:
                new = list(configured)
                for mac, kind, key in pending:
                    instance = resolve_instance(hub, kind, new)
                    new.append(
                        {"address": mac, "key": key, "kind": kind, "instance": instance}
                    )
                remove = set(user_input.get("remove", []))
                new = [d for d in new if d["address"] not in remove]
                # Un-ignore: drop the ticked MACs so they can be discovered again.
                unignore = {m.upper() for m in user_input.get("unignore", [])}
                new_ignored = [m for m in ignored if m not in unignore]
                if user_input.get("clear_ignored"):
                    new_ignored = []
                return self.async_create_entry(
                    title="",
                    data={
                        **options,
                        CONF_BLE_DEVICES: new,
                        CONF_BLE_IGNORED: new_ignored,
                        CONF_BLE_DISCOVERY: bool(
                            user_input.get(CONF_BLE_DISCOVERY, discovery_enabled(options))
                        ),
                    },
                )
            # fall through to re-show the form with the error
        else:
            errors = {}

        fields: dict = {
            vol.Required(
                CONF_BLE_DISCOVERY, default=discovery_enabled(options)
            ): bool,
        }
        for mac, _kind in discovered:
            # NOTE: runtime-generated field key -> the label shows the raw key;
            # the MAC is embedded so it's still identifiable (same known HA
            # translation limitation as the per-instance name fields).
            fields[vol.Optional(f"key_{mac}")] = str
        if configured:
            fields[vol.Optional("remove", default=[])] = cv.multi_select(
                {
                    d["address"]: f"{KIND_LABELS.get(d['kind'], d['kind'])} "
                    f"{d['address']} \u2192 instance {d['instance']}"
                    for d in configured
                }
            )
        if ignored:
            fields[vol.Optional("unignore", default=[])] = cv.multi_select(
                {mac: mac for mac in ignored}
            )
            fields[vol.Optional("clear_ignored", default=False)] = bool

        # Human-readable summary for the step description.
        disc_lines = [f"\u2022 {KIND_LABELS.get(k, k)} — {m}" for m, k in discovered]
        conf_lines = [
            f"\u2022 {KIND_LABELS.get(d['kind'], d['kind'])} — {d['address']}"
            for d in configured
        ]
        summary = ""
        if disc_lines:
            summary += "Discovered (need a key):\n" + "\n".join(disc_lines) + "\n\n"
        else:
            summary += "No un-keyed Victron devices are advertising right now.\n\n"
        if conf_lines:
            summary += "Already configured:\n" + "\n".join(conf_lines) + "\n\n"
        if ignored:
            summary += "Ignored (tick to un-ignore):\n" + "\n".join(
                f"\u2022 {m}" for m in ignored
            )

        return self.async_show_form(
            step_id="ble",
            data_schema=vol.Schema(fields),
            description_placeholders={"summary": summary},
            errors=errors,
        )
