"""Keep diagnostic state account-scoped and drain its pending storage writes."""

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from custom_components.myq.exceptions import MyQApiError
from custom_components.myq.keypad_diagnostics import KeypadDiagnostics
from custom_components.myq.keypad_state import KeypadPower
from custom_components.myq.models import MyQCamera

KEYPAD = MyQCamera("TC-0007-20000001", True, "vkp-camera")


async def test_session_and_preview_updates_stay_local_and_isolated_by_account(
    hass: HomeAssistant,
) -> None:
    read_power, changed = AsyncMock(), MagicMock()
    first = KeypadDiagnostics(hass, "first", lambda: (KEYPAD,), read_power, changed)
    second = KeypadDiagnostics(hass, "second", lambda: (KEYPAD,), read_power, MagicMock())
    first_preview, second_preview = MagicMock(), MagicMock()
    remove_first = async_dispatcher_connect(
        hass, first.snapshot_signal(KEYPAD.serial_number), first_preview
    )
    remove_second = async_dispatcher_connect(
        hass, second.snapshot_signal(KEYPAD.serial_number), second_preview
    )
    try:
        first.async_token_refreshed()
        first.async_stream_event(KEYPAD.serial_number, "start", None)
        first.async_stream_event(KEYPAD.serial_number, "first_frame", 1.5)
        at = datetime.now(UTC)
        first.async_set_snapshot_time(KEYPAD.serial_number, at)
        await hass.async_block_till_done()
        state = first.state(KEYPAD.serial_number)
        assert state.credential_renewals == 1
        assert state.session_active and state.first_frame_seconds == 1.5
        assert first.snapshot_time(KEYPAD.serial_number) == at
        assert second.snapshot_time(KEYPAD.serial_number) is None
        assert second.state(KEYPAD.serial_number).credential_renewals == 0
        assert not second.state(KEYPAD.serial_number).session_active
        first_preview.assert_called_once()
        second_preview.assert_not_called()
        assert changed.call_count == 3
        read_power.assert_not_awaited()
    finally:
        remove_first()
        remove_second()
        await first.async_shutdown()
        await second.async_shutdown()


async def test_shutdown_drains_storage_without_publishing_late_power(hass: HomeAssistant) -> None:
    started, release = asyncio.Event(), asyncio.Event()

    async def save(data: dict[str, object]) -> None:
        started.set()
        await release.wait()

    changed = MagicMock()
    diagnostics = KeypadDiagnostics(
        hass,
        "entry",
        lambda: (KEYPAD,),
        AsyncMock(return_value=KeypadPower(time.time(), 70, "LPDS")),
        changed,
    )
    diagnostics._store = MagicMock(async_save=AsyncMock(side_effect=save))
    refresh = asyncio.create_task(diagnostics.async_refresh_power(KEYPAD.serial_number))
    await started.wait()
    shutdown = asyncio.create_task(diagnostics.async_shutdown())
    await asyncio.sleep(0)
    assert not shutdown.done()
    release.set()
    await asyncio.gather(refresh, shutdown)
    assert diagnostics.state(KEYPAD.serial_number).power is None
    assert not diagnostics._power_expiry
    changed.assert_not_called()
    with pytest.raises(MyQApiError, match="shut down"):
        await diagnostics.async_refresh_power(KEYPAD.serial_number)
