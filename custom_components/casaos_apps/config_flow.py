"""Add a CasaOS / ZimaOS server with the same login as its web UI."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DOMAIN
from .api import AuthError, CasaOSClient, CasaOSError

SCHEMA = vol.Schema({vol.Required(CONF_NAME): str, vol.Required(CONF_HOST): str, vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})


class CasaOSAppsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            client = CasaOSClient(async_get_clientsession(self.hass), user_input[CONF_HOST], user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            try:
                await client.login()
                await client.apps()
            except AuthError:
                errors["base"] = "invalid_auth"
            except (CasaOSError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                data = {k: user_input[k] for k in (CONF_HOST, CONF_USERNAME, CONF_PASSWORD)}
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)
        return self.async_show_form(step_id="user", data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input or {}), errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]):
        """The server rejected the saved login (password changed): ask for the new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            client = CasaOSClient(async_get_clientsession(self.hass), entry.data[CONF_HOST], user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            try:
                await client.login()
            except AuthError:
                errors["base"] = "invalid_auth"
            except (CasaOSError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        schema = vol.Schema({vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str, vol.Required(CONF_PASSWORD): str})
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors,
                                    description_placeholders={"host": entry.data[CONF_HOST]})
