"""Home Assistant light services, identity and reported state."""

from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientConnectionError
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myq.client import MyQClient
from custom_components.myq.const import (
    COMMAND_UPDATE_INITIAL_INTERVAL,
    CONF_EMAIL,
    CONF_MFA_METHOD,
    CONF_TOKENS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    MFA_METHOD_EMAIL,
)
from custom_components.myq.exceptions import (
    MyQApiError,
    MyQAuthenticationError,
    MyQRateLimitError,
)
from custom_components.myq.light import MyQLightEntity
from custom_components.myq.models import MyQDevices, MyQLight
from custom_components.myq.runtime import MyQConfigEntry

FIRST = MyQLight("account-1", "lamp-1", "Porch", "myq-light", "off", True)
SECOND = MyQLight("account-2", "lamp-2", "Hall", "myq-light", "on", True)
type LightSetup = tuple[MyQConfigEntry, MagicMock, tuple[str, str]]


@pytest.fixture
async def light_setup(hass: HomeAssistant) -> AsyncGenerator[LightSetup]:
    mock_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="driver@example.com",
        data={
            CONF_EMAIL: "driver@example.com",
            CONF_MFA_METHOD: MFA_METHOD_EMAIL,
            CONF_TOKENS: {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": 9876543210.0,
            },
        },
    )
    mock_entry.add_to_hass(hass)
    entry = cast(MyQConfigEntry, mock_entry)
    client = MagicMock(spec=MyQClient)
    client.async_get_devices = AsyncMock(return_value=MyQDevices(lights=(FIRST, SECOND)))
    with patch("custom_components.myq.MyQClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    first_id = registry.async_get_entity_id("light", DOMAIN, FIRST.serial_number)
    second_id = registry.async_get_entity_id("light", DOMAIN, SECOND.serial_number)
    assert first_id is not None and second_id is not None and first_id != second_id
    coordinator = entry.runtime_data.coordinator
    yield entry, client, (first_id, second_id)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.is_state(first_id, STATE_UNAVAILABLE)
    assert hass.states.is_state(second_id, STATE_UNAVAILABLE)
    assert not coordinator._listeners


async def test_light_only_account_registers_named_devices(
    hass: HomeAssistant, light_setup: LightSetup
) -> None:
    entry, client, ids = light_setup
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    for light, entity_id in zip((FIRST, SECOND), ids, strict=True):
        entity = registry.async_get(entity_id)
        device = devices.async_get_device(identifiers={(DOMAIN, light.serial_number)})
        assert entity is not None and entity.disabled_by is None
        assert device is not None and device.id == entity.device_id
        assert device.name == light.name and device.model == light.device_model
        assert device.manufacturer == MANUFACTURER
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == light.lamp_state
        assert state.attributes["friendly_name"] == light.name
        assert state.attributes["supported_color_modes"] == ["onoff"]
        assert state.attributes.get("brightness") is None
    assert entry.runtime_data.coordinator.data == {}
    assert entry.runtime_data.coordinator.cameras == {}
    client.async_get_devices.assert_awaited_once()
    client.async_turn_on_light.assert_not_awaited()
    client.async_turn_off_light.assert_not_awaited()


async def test_services_control_each_light_and_wait_for_reported_state(
    hass: HomeAssistant, light_setup: LightSetup
) -> None:
    entry, client, (first_id, second_id) = light_setup
    coordinator = entry.runtime_data.coordinator

    await hass.services.async_call("light", "turn_on", {"entity_id": first_id}, blocking=True)
    await hass.services.async_call("light", "turn_off", {"entity_id": second_id}, blocking=True)
    await hass.async_block_till_done()

    client.async_turn_on_light.assert_awaited_once_with(FIRST)
    client.async_turn_off_light.assert_awaited_once_with(SECOND)
    assert hass.states.is_state(first_id, "off")
    assert hass.states.is_state(second_id, "on")
    assert coordinator.update_interval == COMMAND_UPDATE_INITIAL_INTERVAL

    client.async_get_devices.return_value = MyQDevices(
        lights=(replace(FIRST, lamp_state="on"), replace(SECOND, lamp_state="off"))
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.is_state(first_id, "on")
    assert hass.states.is_state(second_id, "off")
    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL
    assert client.async_get_devices.await_count == 2


@pytest.mark.parametrize(
    ("lamp_state", "online", "expected"),
    [
        ("on", True, "on"),
        ("off", True, "off"),
        (None, True, STATE_UNKNOWN),
        ("unexpected", None, STATE_UNKNOWN),
        ("on", False, STATE_UNAVAILABLE),
    ],
)
async def test_light_state_tracks_cloud_reports_without_door_changes(
    hass: HomeAssistant,
    light_setup: LightSetup,
    lamp_state: str | None,
    online: bool | None,
    expected: str,
) -> None:
    entry, client, (first_id, second_id) = light_setup
    client.async_get_devices.return_value = MyQDevices(
        lights=(replace(FIRST, lamp_state=lamp_state, online=online), SECOND)
    )

    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.is_state(first_id, expected)
    assert hass.states.is_state(second_id, "on")


async def test_missing_and_failed_lights_become_unavailable_and_recover(
    hass: HomeAssistant, light_setup: LightSetup
) -> None:
    entry, client, (first_id, second_id) = light_setup
    coordinator = entry.runtime_data.coordinator
    client.async_get_devices.return_value = MyQDevices(lights=(SECOND,))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.is_state(first_id, STATE_UNAVAILABLE)
    assert hass.states.is_state(second_id, "on")

    client.async_get_devices.side_effect = ClientConnectionError
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.is_state(second_id, STATE_UNAVAILABLE)

    client.async_get_devices.side_effect = None
    client.async_get_devices.return_value = MyQDevices(lights=(FIRST, SECOND))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.is_state(first_id, "off")
    assert hass.states.is_state(second_id, "on")


@pytest.mark.parametrize(
    "error",
    [
        MyQApiError(),
        MyQAuthenticationError(),
        MyQRateLimitError(60),
        ClientConnectionError(),
        TimeoutError(),
    ],
)
async def test_failed_commands_report_errors_without_polling_or_changing_state(
    hass: HomeAssistant, light_setup: LightSetup, error: Exception
) -> None:
    entry, client, (first_id, _) = light_setup
    client.async_turn_on_light.side_effect = error

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("light", "turn_on", {"entity_id": first_id}, blocking=True)

    assert hass.states.is_state(first_id, "off")
    assert entry.runtime_data.coordinator.update_interval == DEFAULT_UPDATE_INTERVAL
    client.async_get_devices.assert_awaited_once()


async def test_missing_light_cannot_receive_a_command(light_setup: LightSetup) -> None:
    entry, client, _ = light_setup
    coordinator = entry.runtime_data.coordinator
    entity = MyQLightEntity(coordinator, FIRST)
    coordinator.lights.clear()

    with pytest.raises(HomeAssistantError):
        await entity.async_turn_on()

    client.async_turn_on_light.assert_not_awaited()
