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

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_CONFIG_PATH,
    CONF_DOMAINS,
    DEFAULT_PORT,
    DOMAIN,
    REQUEST_TIMEOUT,
    SUPPORTED_DOMAINS,
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

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._config: dict[str, Any] = {}
        self._enabled: dict[int, str] = {}
        self._reconfigure_entry = None

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry point for re-running onboarding on an existing entry."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        self._host = self._reconfigure_entry.data.get(CONF_HOST)
        self._port = self._reconfigure_entry.data.get(CONF_PORT, DEFAULT_PORT)
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

            data = {
                CONF_HOST: self._host,
                CONF_PORT: self._port,
                CONF_DOMAINS: domains,
            }
            if self._reconfigure_entry is not None:
                return self.async_update_reload_and_abort(
                    self._reconfigure_entry, data=data
                )
            return self.async_create_entry(
                title=f"Waymote ({self._host})", data=data
            )

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
