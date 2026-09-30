# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Config flow for Clever Caravan: Waymote.

Two steps:
  1. user     - enter the bridge address; validated against GET /api/config.
  2. outputs  - one screen listing every output. Each row is pre-filled with its
                real name where one exists, blank where the name is still the
                generic "Output N". A blank row means "hide this output". On
                submit, the choices are written back to the bridge via
                POST /api/config, so config.json stays the single source of truth.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_CONFIG_PATH,
    COMBO_AWNING,
    COMBO_TWO_TONE,
    CONF_AWNING_POWER_OFF_MINUTES,
    CONF_AWNING_STOP_CUTS_POWER,
    DEFAULT_AWNING_POWER_OFF_MINUTES,
    DEFAULT_AWNING_STOP_CUTS_POWER,
    CONF_COMBOS,
    CONF_DOMAINS,
    DEFAULT_PORT,
    DOMAIN,
    REQUEST_TIMEOUT,
    SUPPORTED_DOMAINS,
    channels_in_combos,
    combo_channels,
    get_combos,
    infer_domain,
)

_LOGGER = logging.getLogger(__name__)


# --- Pure helpers (no hass needed; unit-tested) ------------------------------

def channels_from_config(config: dict[str, Any]) -> list[int]:
    """Sorted list of output channel numbers present in the config."""
    outputs = config.get("outputs", {}) or {}
    return sorted(int(k) for k in outputs if str(k).isdigit())


def is_generic_name(channel: int, name: str) -> bool:
    """True if the name is still the factory placeholder for this channel."""
    return (name or "").strip() == f"Output {channel}"


def naming_defaults(config: dict[str, Any]) -> dict[int, str]:
    """Per-channel default for the form: real name, or blank if still generic."""
    outputs = config.get("outputs", {}) or {}
    defaults: dict[int, str] = {}
    for channel in channels_from_config(config):
        name = str(outputs.get(str(channel), {}).get("name", f"Output {channel}"))
        defaults[channel] = "" if is_generic_name(channel, name) else name
    return defaults


def channel_from_field_key(key: str) -> int | None:
    """Parse the channel number out of a form field key like 'Output 5'."""
    try:
        return int(key.rsplit(" ", 1)[1])
    except (IndexError, ValueError):
        return None


def build_outputs_payload(user_input: dict[str, str]) -> dict[str, Any]:
    """Turn submitted name fields into a POST /api/config body.

    Filled name -> enabled=True with that name.
    Blank name  -> enabled=False, name reset to the generic placeholder (hidden).
    """
    outputs: dict[str, Any] = {}
    for key, value in user_input.items():
        channel = channel_from_field_key(key)
        if channel is None:
            continue
        name = (value or "").strip()
        if name:
            outputs[str(channel)] = {"name": name, "enabled": True}
        else:
            outputs[str(channel)] = {"name": f"Output {channel}", "enabled": False}
    return {"outputs": outputs}


# --- Flow --------------------------------------------------------------------

class WaymoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a Waymote bridge."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> "WaymoteOptionsFlow":
        return WaymoteOptionsFlow()

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._config: dict[str, Any] = {}
        self._enabled: dict[int, str] = {}
        self._domains: dict[str, str] = {}
        self._combos: list[dict[str, Any]] = []
        self._existing_combos: list[dict[str, Any]] = []
        self._reconfigure_entry = None

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point for re-running onboarding on an existing entry."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        self._host = self._reconfigure_entry.data.get(CONF_HOST)
        self._port = self._reconfigure_entry.data.get(CONF_PORT, DEFAULT_PORT)
        # Carry the existing combined devices through, so walking the flow again
        # does not wipe them.
        self._existing_combos = list(get_combos(self._reconfigure_entry))
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            url = f"http://{host}:{port}{API_CONFIG_PATH}"
            session = async_get_clientsession(self.hass)

            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    resp = await session.get(url)
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                if not isinstance(data, dict) or "outputs" not in data:
                    errors["base"] = "invalid_response"
                else:
                    if self._reconfigure_entry is None:
                        await self.async_set_unique_id(f"{host}:{port}")
                        self._abort_if_unique_id_configured()
                    self._host = host
                    self._port = port
                    self._config = data
                    return await self.async_step_outputs()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._host or vol.UNDEFINED): str,
                vol.Optional(CONF_PORT, default=self._port): int,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_outputs(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            payload = build_outputs_payload(user_input)
            url = f"http://{self._host}:{self._port}{API_CONFIG_PATH}"
            session = async_get_clientsession(self.hass)
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    resp = await session.post(url, json=payload)
                    resp.raise_for_status()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                errors["base"] = "write_failed"
            else:
                # Remember which outputs are now enabled (non-blank names) so the
                # next step only asks about those.
                self._enabled = {
                    int(ch): entry["name"]
                    for ch, entry in payload["outputs"].items()
                    if entry.get("enabled")
                }
                return await self.async_step_domains()

        defaults = naming_defaults(self._config)
        fields: dict[Any, Any] = {}
        for channel in channels_from_config(self._config):
            fields[
                vol.Optional(f"Output {channel}", default=defaults.get(channel, ""))
            ] = str
        schema = vol.Schema(fields)

        return self.async_show_form(
            step_id="outputs", data_schema=schema, errors=errors
        )

    async def async_step_domains(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            domains: dict[str, str] = {}
            for key, value in user_input.items():
                channel = channel_from_field_key(key)
                if channel is not None:
                    domains[str(channel)] = value
            self._domains = domains
            self._combos = [
                combo
                for combo in self._existing_combos
                if all(ch in self._enabled for ch in combo_channels(combo))
            ]
            return await self.async_step_combine()

        fields: dict[Any, Any] = {}
        for channel in sorted(self._enabled):
            name = self._enabled[channel]
            fields[
                vol.Optional(
                    f"{name} \u2014 Output {channel}",
                    default=infer_domain(name),
                )
            ] = vol.In(SUPPORTED_DOMAINS)
        schema = vol.Schema(fields)

        return self.async_show_form(step_id="domains", data_schema=schema)

    # --- combined devices --------------------------------------------------

    def _finish(self) -> ConfigFlowResult:
        data = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_DOMAINS: self._domains,
            CONF_COMBOS: self._combos,
        }
        if self._reconfigure_entry is not None:
            options = dict(self._reconfigure_entry.options)
            options[CONF_COMBOS] = self._combos
            return self.async_update_reload_and_abort(
                self._reconfigure_entry, data=data, options=options
            )
        return self.async_create_entry(title=f"Waymote ({self._host})", data=data)

    def _free_channels(self) -> dict[int, str]:
        """Enabled outputs not already consumed by a combo."""
        used = channels_in_combos(self._combos)
        return {ch: name for ch, name in self._enabled.items() if ch not in used}

    async def async_step_combine(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to combine outputs into a single device, or finish."""
        if len(self._free_channels()) < 2:
            return self._finish()
        options = ["two_tone"]
        if len(self._free_channels()) >= 3:
            options.append("awning")
        options.append("finish")
        return self.async_show_menu(step_id="combine", menu_options=options)

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self._finish()

    async def async_step_two_tone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Combine two outputs (e.g. White + Ambient) into one light."""
        errors: dict[str, str] = {}
        free = self._free_channels()

        if user_input is not None:
            white = int(user_input["white"])
            ambient = int(user_input["ambient"])
            if white == ambient:
                errors["base"] = "same_output"
            else:
                self._combos.append(
                    {
                        "type": COMBO_TWO_TONE,
                        "name": user_input["name"].strip()
                        or f"Light {white}/{ambient}",
                        "white": white,
                        "ambient": ambient,
                    }
                )
                return await self.async_step_combine()

        options = {str(ch): f"{name} \u2014 Output {ch}" for ch, name in sorted(free.items())}
        schema = vol.Schema(
            {
                vol.Required("name"): str,
                vol.Required("white"): vol.In(options),
                vol.Required("ambient"): vol.In(options),
            }
        )
        return self.async_show_form(
            step_id="two_tone", data_schema=schema, errors=errors
        )

    async def async_step_awning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Combine Power + Extend + Retract into one awning."""
        errors: dict[str, str] = {}
        free = self._free_channels()

        if user_input is not None:
            power = int(user_input["power"])
            extend = int(user_input["extend"])
            retract = int(user_input["retract"])
            if len({power, extend, retract}) < 3:
                errors["base"] = "same_output"
            else:
                self._combos.append(
                    {
                        "type": COMBO_AWNING,
                        "name": user_input["name"].strip() or f"Awning {power}",
                        "power": power,
                        "extend": extend,
                        "retract": retract,
                    }
                )
                return await self.async_step_combine()

        options = {str(ch): f"{name} \u2014 Output {ch}" for ch, name in sorted(free.items())}
        schema = vol.Schema(
            {
                vol.Required("name"): str,
                vol.Required("power"): vol.In(options),
                vol.Required("extend"): vol.In(options),
                vol.Required("retract"): vol.In(options),
            }
        )
        return self.async_show_form(
            step_id="awning", data_schema=schema, errors=errors
        )


class WaymoteOptionsFlow(OptionsFlow):
    """Settings and combined devices, from the integration's Configure button.

    Editing combos here avoids re-running onboarding (which would ask for every
    output name again) just to add or remove one device.
    """

    def __init__(self) -> None:
        self._combos: list[dict[str, Any]] | None = None

    # --- helpers -----------------------------------------------------------

    @property
    def _entry(self):
        return self.config_entry

    def _current_combos(self) -> list[dict[str, Any]]:
        if self._combos is None:
            self._combos = [dict(c) for c in get_combos(self._entry)]
        return self._combos

    def _enabled_outputs(self) -> dict[int, str]:
        """Enabled outputs and their names, read from the bridge's config."""
        coordinator = getattr(self._entry, "runtime_data", None)
        outputs = ((getattr(coordinator, "data", None) or {}).get("outputs") or {})
        result: dict[int, str] = {}
        for key, cfg in outputs.items():
            if str(key).isdigit() and isinstance(cfg, dict) and cfg.get("enabled"):
                result[int(key)] = cfg.get("name", f"Output {key}")
        return result

    def _free_channels(self) -> dict[int, str]:
        used = channels_in_combos(self._current_combos())
        return {ch: n for ch, n in self._enabled_outputs().items() if ch not in used}

    def _save(self) -> ConfigFlowResult:
        options = dict(self._entry.options)
        options[CONF_COMBOS] = self._current_combos()
        options.setdefault(
            CONF_AWNING_POWER_OFF_MINUTES, DEFAULT_AWNING_POWER_OFF_MINUTES
        )
        options.setdefault(
            CONF_AWNING_STOP_CUTS_POWER, DEFAULT_AWNING_STOP_CUTS_POWER
        )
        # Explicit reload so new or removed devices appear straight away,
        # without an update listener.
        self.hass.config_entries.async_schedule_reload(self._entry.entry_id)
        return self.async_create_entry(data=options)

    # --- menu --------------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["settings"]
        free = self._free_channels()
        if len(free) >= 2:
            options.append("add_two_tone")
        if len(free) >= 3:
            options.append("add_awning")
        if self._current_combos():
            options.append("remove_combo")
        options.append("save")
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self._save()

    # --- settings ----------------------------------------------------------

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = dict(self._entry.options)
            options.update(user_input)
            options[CONF_COMBOS] = self._current_combos()
            self.hass.config_entries.async_schedule_reload(self._entry.entry_id)
            return self.async_create_entry(data=options)

        opts = self._entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_AWNING_POWER_OFF_MINUTES,
                    default=opts.get(
                        CONF_AWNING_POWER_OFF_MINUTES,
                        DEFAULT_AWNING_POWER_OFF_MINUTES,
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
                vol.Optional(
                    CONF_AWNING_STOP_CUTS_POWER,
                    default=opts.get(
                        CONF_AWNING_STOP_CUTS_POWER,
                        DEFAULT_AWNING_STOP_CUTS_POWER,
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    # --- add / remove combined devices -------------------------------------

    async def async_step_add_two_tone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        free = self._free_channels()

        if user_input is not None:
            white, ambient = int(user_input["white"]), int(user_input["ambient"])
            if white == ambient:
                errors["base"] = "same_output"
            else:
                self._current_combos().append(
                    {
                        "type": COMBO_TWO_TONE,
                        "name": user_input["name"].strip() or f"Light {white}/{ambient}",
                        "white": white,
                        "ambient": ambient,
                    }
                )
                return await self.async_step_init()

        options = {str(ch): f"{n} \u2014 Output {ch}" for ch, n in sorted(free.items())}
        schema = vol.Schema(
            {
                vol.Required("name"): str,
                vol.Required("white"): vol.In(options),
                vol.Required("ambient"): vol.In(options),
            }
        )
        return self.async_show_form(
            step_id="add_two_tone", data_schema=schema, errors=errors
        )

    async def async_step_add_awning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        free = self._free_channels()

        if user_input is not None:
            power = int(user_input["power"])
            extend = int(user_input["extend"])
            retract = int(user_input["retract"])
            if len({power, extend, retract}) < 3:
                errors["base"] = "same_output"
            else:
                self._current_combos().append(
                    {
                        "type": COMBO_AWNING,
                        "name": user_input["name"].strip() or f"Awning {power}",
                        "power": power,
                        "extend": extend,
                        "retract": retract,
                    }
                )
                return await self.async_step_init()

        options = {str(ch): f"{n} \u2014 Output {ch}" for ch, n in sorted(free.items())}
        schema = vol.Schema(
            {
                vol.Required("name"): str,
                vol.Required("power"): vol.In(options),
                vol.Required("extend"): vol.In(options),
                vol.Required("retract"): vol.In(options),
            }
        )
        return self.async_show_form(
            step_id="add_awning", data_schema=schema, errors=errors
        )

    async def async_step_remove_combo(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        combos = self._current_combos()

        if user_input is not None:
            index = int(user_input["combo"])
            if 0 <= index < len(combos):
                combos.pop(index)
            return await self.async_step_init()

        options = {
            str(i): f"{c.get('name')} ({'awning' if c.get('type') == COMBO_AWNING else 'two-tone light'})"
            for i, c in enumerate(combos)
        }
        schema = vol.Schema({vol.Required("combo"): vol.In(options)})
        return self.async_show_form(step_id="remove_combo", data_schema=schema)
