"""Reauth flow with Home Assistant's test harness. Run: pip install pytest-homeassistant-custom-component; python -m pytest tests"""
from unittest.mock import patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402

from custom_components.casaos_apps.api import AuthError  # noqa: E402

DATA = {"host": "192.0.2.10", "username": "admin", "password": "old"}
LOGIN = "custom_components.casaos_apps.api.CasaOSClient.login"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def test_rejected_login_at_setup_starts_reauth_and_new_password_is_saved(hass):
    entry = MockConfigEntry(domain="casaos_apps", title="NAS", unique_id=DATA["host"], data=DATA)
    entry.add_to_hass(hass)
    with patch(LOGIN, side_effect=AuthError("wrong password")):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]

    with patch(LOGIN, side_effect=AuthError("still wrong")):
        res = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"username": "admin", "password": "bad"})
    assert res["type"] is FlowResultType.FORM and res["errors"] == {"base": "invalid_auth"}

    with patch(LOGIN, return_value=None):
        res = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"username": "admin", "password": "new"})
        await hass.async_block_till_done()
    assert res["type"] is FlowResultType.ABORT and res["reason"] == "reauth_successful"
    assert entry.data["password"] == "new" and entry.data["host"] == DATA["host"]
    assert entry.state is ConfigEntryState.LOADED
