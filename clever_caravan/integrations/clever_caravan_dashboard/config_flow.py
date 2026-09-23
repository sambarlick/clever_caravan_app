# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Config and options flow for Clever Caravan Dashboard."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_EXTRA_PLATFORMS,
    CONF_ROLE_MAP,
    CONF_TIER,
    DOMAIN,
    OWNED_PLATFORMS,
    TIER_BASE,
    TIERS,
)


class CleverCaravanDashboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance setup flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Clever Caravan: Dashboard", data={})

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return CleverCaravanDashboardOptionsFlow()


class CleverCaravanDashboardOptionsFlow(OptionsFlow):
    """Installer settings: tier + extra integrations to include."""

    def _integration_options(self) -> list[selector.SelectOptionDict]:
        """Installed integrations the installer can add to the dashboard."""
        skip = {DOMAIN, *OWNED_PLATFORMS}
        titles: dict[str, str] = {}
        for entry in self.hass.config_entries.async_entries():
            if entry.domain in skip:
                continue
            titles.setdefault(entry.domain, entry.title or entry.domain)
        return [
            selector.SelectOptionDict(value=domain, label=f"{title} ({domain})")
            for domain, title in sorted(titles.items(), key=lambda kv: kv[1].lower())
        ]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        options = dict(self.config_entry.options)

        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_TIER: user_input[CONF_TIER],
                    CONF_EXTRA_PLATFORMS: user_input.get(CONF_EXTRA_PLATFORMS, []),
                    CONF_ROLE_MAP: options.get(CONF_ROLE_MAP, {}),
                },
            )

        available = self._integration_options()
        valid = {opt["value"] for opt in available}
        # Drop previously-selected integrations that are no longer installed,
        # otherwise the form fails validation.
        current = [d for d in options.get(CONF_EXTRA_PLATFORMS, []) if d in valid]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TIER, default=options.get(CONF_TIER, TIER_BASE)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=TIERS,
                        translation_key="tier",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_EXTRA_PLATFORMS, default=current
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=available,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
