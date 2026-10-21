"""CasaOS / ZimaOS apps: read and edit each app's compose settings from Home Assistant.

Talks to the same app management API the CasaOS / ZimaOS web UI uses, so a save here is the same as pressing
Save in their "Edit app" window. The ⋯ menu card (casaos-app-menu.js) is served by this integration.
All commands are admin-only: compose files hold secrets, and applying one recreates containers.
"""
from __future__ import annotations

import time
from pathlib import Path

import aiohttp
import voluptuous as vol
import yaml

from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from urllib.parse import urlparse

from .api import CasaOSClient, CasaOSError, PortainerClient, find_app

DOMAIN = "casaos_apps"
CARD_URL = "/casaos_apps/casaos-app-menu.js"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
APPS_CACHE_S = 60


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(Path(__file__).parent / "www" / "casaos-app-menu.js"), cache_headers=False)]
    )
    for cmd in (ws_servers, ws_app, ws_convert, ws_save):
        websocket_api.async_register_command(hass, cmd)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = CasaOSClient(async_get_clientsession(hass), entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    hass.data[DOMAIN][entry.entry_id] = {"client": client, "entry": entry, "apps": None, "at": 0.0}
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True


def _server(hass: HomeAssistant, name: str) -> dict:
    """A server by its entry title (any case) or host."""
    for srv in hass.data[DOMAIN].values():
        if name.lower() in (srv["entry"].title.lower(), srv["entry"].data[CONF_HOST]):
            return srv
    raise CasaOSError(f"no CasaOS server called {name!r}")


async def _apps(srv: dict, fresh: bool = False) -> dict:
    if fresh or srv["apps"] is None or time.monotonic() - srv["at"] > APPS_CACHE_S:
        srv["apps"], srv["at"] = await srv["client"].apps(), time.monotonic()
    return srv["apps"]


@websocket_api.websocket_command({vol.Required("type"): "casaos_apps/servers"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_servers(hass, connection, msg):
    connection.send_result(msg["id"], [{"title": s["entry"].title, "host": s["entry"].data[CONF_HOST]} for s in hass.data[DOMAIN].values()])


@websocket_api.websocket_command({vol.Required("type"): "casaos_apps/app", vol.Required("server"): str, vol.Required("container"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_app(hass, connection, msg):
    try:
        srv = _server(hass, msg["server"])
        app_id = find_app(await _apps(srv), msg["container"]) or find_app(await _apps(srv, fresh=True), msg["container"])
        host = srv["entry"].data[CONF_HOST]
        if app_id:
            text = await srv["client"].compose_yaml(app_id)
            result = {"app_id": app_id, "host": host, "yaml": text, "compose": yaml.safe_load(text), "readonly": False}
        else:  # made with `docker run`: CasaOS can't edit it; show its settings read-only through HA's Portainer integration
            portainer = next((e for e in hass.config_entries.async_entries("portainer") if urlparse(e.data.get("url", "")).hostname == host), None)
            if not portainer:
                raise CasaOSError(f"{msg['container']} is not a CasaOS app on {srv['entry'].title}, and there's no Portainer integration for {host}")
            compose = await PortainerClient(async_get_clientsession(hass, verify_ssl=False), portainer.data["url"], portainer.data["api_token"]).compose(msg["container"])
            result = {"app_id": None, "host": host, "compose": compose, "readonly": True,
                      "yaml": yaml.safe_dump(compose, sort_keys=False, allow_unicode=True)}
    except (CasaOSError, aiohttp.ClientError, TimeoutError) as err:
        connection.send_error(msg["id"], "casaos_error", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({
    vol.Required("type"): "casaos_apps/convert",
    vol.Exclusive("yaml", "content"): str,
    vol.Exclusive("compose", "content"): dict,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_convert(hass, connection, msg):
    """Form <-> YAML tab switch: YAML text to a compose object, or back."""
    if "compose" in msg:
        connection.send_result(msg["id"], {"yaml": yaml.safe_dump(msg["compose"], sort_keys=False, allow_unicode=True)})
        return
    try:
        compose = yaml.safe_load(msg.get("yaml") or "")
    except yaml.YAMLError as err:
        connection.send_error(msg["id"], "invalid_yaml", str(err))
        return
    if not isinstance(compose, dict):
        connection.send_error(msg["id"], "invalid_yaml", "not a compose file")
        return
    connection.send_result(msg["id"], {"compose": compose})


@websocket_api.websocket_command({
    vol.Required("type"): "casaos_apps/save",
    vol.Required("server"): str,
    vol.Required("app_id"): str,
    vol.Exclusive("yaml", "content"): str,
    vol.Exclusive("compose", "content"): dict,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save(hass, connection, msg):
    """Validate (dry run) and then apply; CasaOS recreates the app's containers."""
    try:
        text = msg.get("yaml")
        if text is None:
            text = yaml.safe_dump(msg["compose"], sort_keys=False, allow_unicode=True)
        if not isinstance(yaml.safe_load(text), dict):
            raise CasaOSError("not a compose file")
        srv = _server(hass, msg["server"])
        await srv["client"].apply(msg["app_id"], text, dry_run=True)
        await srv["client"].apply(msg["app_id"], text, dry_run=False)
        srv["apps"] = None
    except yaml.YAMLError as err:
        connection.send_error(msg["id"], "invalid_yaml", str(err))
        return
    except CasaOSError as err:
        connection.send_error(msg["id"], "casaos_error", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})
