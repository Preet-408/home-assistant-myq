"""Standalone light discovery and account-scoped command contracts."""

import json
from dataclasses import replace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientSession

from custom_components.myq.client import MyQClient
from custom_components.myq.discovery import parse_light
from custom_components.myq.exceptions import (
    MyQApiError,
    MyQAuthenticationError,
    MyQRateLimitError,
)
from custom_components.myq.models import MyQLight
from custom_components.myq.oauth import MyQAuth

from .http import FakeResponse, FakeSession

LIGHT = MyQLight("account-1", "lamp-1", "Porch", "myq-light", "off", True)


def _client(session: FakeSession) -> MyQClient:
    auth = MagicMock(spec=MyQAuth)
    auth.async_access_token = AsyncMock(return_value="access")
    return MyQClient(cast(ClientSession, session), auth)


def _item(**values: object) -> dict[str, object]:
    return {
        "device_family": "lamp",
        "serial_number": "lamp-1",
        "name": "Porch",
        "device_model": "myq-light",
        "state": {"lamp_state": "off", "online": True},
        **values,
    }


async def test_discovery_keeps_lights_in_their_owning_accounts() -> None:
    session = FakeSession(
        request_responses=[
            FakeResponse("", body='{"accounts":[{"id":"account-1"},{"id":"account-2"}]}'),
            FakeResponse("", body=json.dumps({"items": [_item()]})),
            FakeResponse(
                "",
                body=json.dumps(
                    {
                        "items": [
                            _item(serial_number="lamp-2", state={"lamp_state": "on"}),
                            {"device_family": "garagedoor", "serial_number": "door-1"},
                            {"device_family": "camera", "serial_number": "TC-0005-10000001"},
                            {"device_family": "gateway", "serial_number": "hub-1"},
                        ]
                    }
                ),
            ),
        ]
    )

    devices = await _client(session).async_get_devices()

    assert devices.lights == (
        LIGHT,
        replace(
            LIGHT, account_id="account-2", serial_number="lamp-2", lamp_state="on", online=None
        ),
    )
    assert devices.lights[0].is_on is False
    assert devices.lights[1].is_on is True
    assert devices.doors[0].account_id == "account-2"
    assert len(devices.doors) == len(devices.cameras) == 1
    assert len(session.calls) == 3
    assert session.calls[1].url.endswith("/Accounts/account-1/Devices")
    assert session.calls[2].url.endswith("/Accounts/account-2/Devices")


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("on", True),
        ("off", False),
        ("ON", True),
        ("unknown", None),
        ("offline", None),
        ("unexpected", None),
        (None, None),
        (False, None),
        (1, None),
    ],
)
def test_light_power_preserves_unknown_values(state: object, expected: bool | None) -> None:
    light = parse_light("account-1", _item(state={"lamp_state": state}))

    assert light.is_on is expected
    assert light.online is None


@pytest.mark.parametrize("state", [None, {}, {"online": "true"}])
def test_light_without_reported_state_remains_unknown(state: object) -> None:
    light = parse_light("account-1", _item(state=state, name=None, device_model=None))

    assert light.is_on is None
    assert light.online is None
    assert light.name == "lamp-1"
    assert light.device_model is None


@pytest.mark.parametrize(
    "invalid",
    [
        {"serial_number": None},
        {"serial_number": ""},
        {"serial_number": 123},
        {"state": []},
        {"state": False},
        {"state": "on"},
    ],
)
def test_malformed_lights_are_rejected(invalid: dict[str, object]) -> None:
    with pytest.raises(MyQApiError):
        parse_light("account-1", _item(**invalid))


async def test_failed_account_does_not_return_partial_light_discovery() -> None:
    session = FakeSession(
        request_responses=[
            FakeResponse("", body='{"accounts":[{"id":"account-1"},{"id":"account-2"}]}'),
            FakeResponse("", body=json.dumps({"items": [_item()]})),
            FakeResponse("", status=500),
        ]
    )

    with pytest.raises(MyQApiError):
        await _client(session).async_get_devices()


async def test_light_commands_use_v6_put_without_a_request_body() -> None:
    session = FakeSession(request_responses=[FakeResponse("", status=204) for _ in range(2)])
    client = _client(session)

    await client.async_turn_on_light(LIGHT)
    await client.async_turn_off_light(
        replace(LIGHT, account_id="account-2", serial_number="lamp-2")
    )

    assert [(call.method, call.url) for call in session.calls] == [
        (
            "PUT",
            "https://account-devices-lamp.myq-cloud.com/api/v6.0/accounts/account-1/lamps/lamp-1/on",
        ),
        (
            "PUT",
            "https://account-devices-lamp.myq-cloud.com/api/v6.0/accounts/account-2/lamps/lamp-2/off",
        ),
    ]
    for call in session.calls:
        assert set(call.kwargs) == {"headers"}
        assert call.kwargs["headers"]["Authorization"] == "Bearer access"


async def test_light_identifiers_cannot_change_the_command_path() -> None:
    session = FakeSession(request_responses=[FakeResponse("", status=204)])

    await _client(session).async_turn_on_light(
        replace(LIGHT, account_id="account/2", serial_number="lamp?#3")
    )

    assert session.calls[0].url == (
        "https://account-devices-lamp.myq-cloud.com/api/v6.0/"
        "accounts/account%2F2/lamps/lamp%3F%233/on"
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, MyQAuthenticationError), (403, MyQAuthenticationError), (500, MyQApiError)],
)
async def test_light_command_http_errors_are_propagated(
    status: int, expected: type[MyQApiError] | type[MyQAuthenticationError]
) -> None:
    session = FakeSession(request_responses=[FakeResponse("", status=status)])

    with pytest.raises(expected):
        await _client(session).async_turn_on_light(LIGHT)

    assert len(session.calls) == 1


async def test_light_commands_share_a_server_requested_cooldown() -> None:
    session = FakeSession(
        request_responses=[FakeResponse("", status=429, headers={"Retry-After": "300"})]
    )
    client = _client(session)

    with pytest.raises(MyQRateLimitError):
        await client.async_turn_on_light(LIGHT)
    with pytest.raises(MyQRateLimitError):
        await client.async_turn_off_light(LIGHT)

    assert len(session.calls) == 1
