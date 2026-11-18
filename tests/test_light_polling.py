"""Bounded light command polling shares discovery with garage doors."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import timedelta
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientConnectionError
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myq.client import MyQClient
from custom_components.myq.const import (
    COMMAND_UPDATE_INITIAL_INTERVAL,
    COMMAND_UPDATE_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.myq.coordinator import MyQDataUpdateCoordinator
from custom_components.myq.models import GarageDoor, MyQDevices, MyQLight

LIGHT = MyQLight("account-1", "lamp-1", "Porch", None, "off", True)
DOOR = GarageDoor("account-1", "door-1", "Garage", None, "closed", True)
type PollingSetup = tuple[MyQDataUpdateCoordinator, MagicMock]


@pytest.fixture
async def light_polling(hass: HomeAssistant) -> AsyncGenerator[PollingSetup]:
    client = MagicMock(spec=MyQClient)
    client.async_get_devices = AsyncMock(return_value=MyQDevices((DOOR,), lights=(LIGHT,)))
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    coordinator = MyQDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_refresh()
    yield coordinator, client
    await coordinator.async_shutdown()


@pytest.mark.parametrize(("initial", "target"), [("off", "on"), ("on", "off")])
async def test_light_polling_stops_when_target_is_confirmed(
    light_polling: PollingSetup, initial: str, target: Literal["on", "off"]
) -> None:
    coordinator, client = light_polling
    client.async_get_devices.return_value = MyQDevices(lights=(replace(LIGHT, lamp_state=initial),))
    with patch("custom_components.myq.coordinator.monotonic", return_value=0) as clock:
        coordinator.async_schedule_command_updates(LIGHT.serial_number, target)
        assert coordinator.update_interval == COMMAND_UPDATE_INITIAL_INTERVAL
        clock.return_value = 1
        await coordinator.async_refresh()
        assert coordinator.update_interval == timedelta(seconds=2)
        client.async_get_devices.return_value = MyQDevices(
            lights=(replace(LIGHT, lamp_state=target),)
        )
        clock.return_value = 3
        await coordinator.async_refresh()

    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL
    assert coordinator.command_motion(LIGHT.serial_number) is None


async def test_unconfirmed_light_command_has_a_bounded_polling_window(
    light_polling: PollingSetup,
) -> None:
    coordinator, _ = light_polling
    with patch("custom_components.myq.coordinator.monotonic", return_value=0) as clock:
        coordinator.async_schedule_command_updates(LIGHT.serial_number, "on")
        for instant, interval in [(1, 2), (3, 3), (6, 4), (10, 5), (59, 5)]:
            clock.return_value = instant
            await coordinator.async_refresh()
            assert coordinator.update_interval == timedelta(seconds=interval)
        clock.return_value = COMMAND_UPDATE_TIMEOUT.total_seconds()
        await coordinator.async_refresh()

    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL
    assert coordinator.lights[LIGHT.serial_number].is_on is False


@pytest.mark.parametrize("missing", [False, True])
async def test_unavailable_light_stops_command_polling(
    light_polling: PollingSetup, missing: bool
) -> None:
    coordinator, client = light_polling
    coordinator.async_schedule_command_updates(LIGHT.serial_number, "on")
    client.async_get_devices.return_value = MyQDevices(
        lights=() if missing else (replace(LIGHT, online=False),)
    )

    await coordinator.async_refresh()

    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL


async def test_light_completion_does_not_stop_an_active_door_command(
    light_polling: PollingSetup,
) -> None:
    coordinator, client = light_polling
    with patch("custom_components.myq.coordinator.monotonic", return_value=0) as clock:
        coordinator.async_schedule_command_updates(DOOR.serial_number, "open")
        coordinator.async_schedule_command_updates(LIGHT.serial_number, "on")
        client.async_get_devices.return_value = MyQDevices(
            (replace(DOOR, door_state="open"),), lights=(replace(LIGHT, lamp_state="on"),)
        )
        clock.return_value = 1
        await coordinator.async_refresh()
        assert coordinator.update_interval == timedelta(seconds=2)
        clock.return_value = 30
        await coordinator.async_refresh()

    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL
    assert client.async_get_devices.await_count == 3


async def test_failed_refresh_preserves_last_light_report_and_stops_fast_polling(
    light_polling: PollingSetup,
) -> None:
    coordinator, client = light_polling
    coordinator.async_schedule_command_updates(LIGHT.serial_number, "on")
    client.async_get_devices.side_effect = ClientConnectionError

    await coordinator.async_refresh()

    assert coordinator.last_update_success is False
    assert coordinator.lights == {LIGHT.serial_number: LIGHT}
    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL


async def test_inflight_refresh_does_not_finish_a_newer_light_command(
    light_polling: PollingSetup,
) -> None:
    coordinator, client = light_polling
    requested = asyncio.Event()
    release = asyncio.Event()

    async def delayed_read() -> MyQDevices:
        requested.set()
        await release.wait()
        return MyQDevices(lights=(LIGHT,))

    with patch("custom_components.myq.coordinator.monotonic", return_value=0) as clock:
        coordinator.async_schedule_command_updates(LIGHT.serial_number, "on")
        client.async_get_devices.side_effect = delayed_read
        refresh = asyncio.create_task(coordinator.async_refresh())
        await requested.wait()
        clock.return_value = 1
        coordinator.async_schedule_command_updates(LIGHT.serial_number, "off")
        release.set()
        await refresh
        assert coordinator.update_interval == COMMAND_UPDATE_INITIAL_INTERVAL
        client.async_get_devices.side_effect = None
        await coordinator.async_refresh()

    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL


async def test_disabled_polling_keeps_manual_light_refresh_available(
    light_polling: PollingSetup,
) -> None:
    coordinator, client = light_polling
    assert coordinator.config_entry is not None
    coordinator.hass.config_entries.async_update_entry(
        coordinator.config_entry, pref_disable_polling=True
    )

    coordinator.async_schedule_command_updates(LIGHT.serial_number, "on")

    assert coordinator.update_interval == DEFAULT_UPDATE_INTERVAL
    client.async_get_devices.return_value = MyQDevices(lights=(replace(LIGHT, lamp_state="on"),))
    await coordinator.async_refresh()
    assert coordinator.lights[LIGHT.serial_number].is_on is True
