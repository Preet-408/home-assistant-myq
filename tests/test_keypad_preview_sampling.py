"""Bound decoder work while retaining the newest passive preview."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.myq.keypad_preview import KeypadPreview

JPEG = b"\xff\xd8synthetic-jpeg"


async def test_live_keyframes_sample_decoder_and_flush_latest_after_stream_ends(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    preview = KeypadPreview(hass, "TC-0007-20000001")
    process = MagicMock(returncode=0, communicate=AsyncMock(return_value=(JPEG, b"")))
    with (
        patch("custom_components.myq.keypad_preview.async_setup_component", return_value=True),
        patch("custom_components.myq.keypad_preview.get_ffmpeg_manager") as manager,
        patch("asyncio.create_subprocess_exec", return_value=process) as spawn,
    ):
        manager.return_value.binary = "ffmpeg"
        for second in range(60):
            if second:
                freezer.tick(timedelta(seconds=1))
            preview.received(f"frame-{second}".encode())
            async_fire_time_changed(hass)
            await hass.async_block_till_done()
        assert spawn.await_count == 2
        assert [call.args[0] for call in process.communicate.await_args_list] == [
            b"frame-0",
            b"frame-30",
        ]
        freezer.tick(timedelta(seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert spawn.await_count == 3
        process.communicate.assert_awaited_with(b"frame-59")
        assert preview.captured_at is not None
        assert preview._conversion_timer is None
        await preview.close()
        assert spawn.await_count == 3


@pytest.mark.parametrize("failure", [None, OSError(), TimeoutError()])
async def test_failed_decoding_still_limits_attempts(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, failure: Exception | None
) -> None:
    preview = KeypadPreview(hass, "TC-0007-20000001")
    with patch.object(preview, "_decode", return_value=None, side_effect=failure) as decode:
        for second in range(60):
            if second:
                freezer.tick(timedelta(seconds=1))
            preview.received(b"invalid-frame")
            async_fire_time_changed(hass)
            await hass.async_block_till_done()
        assert decode.await_count == 2
        assert await preview.image() is None
        await preview.close()


async def test_frames_arriving_during_conversion_wait_and_keep_only_latest(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    preview = KeypadPreview(hass, "TC-0007-20000001")
    started, release = asyncio.Event(), asyncio.Event()

    async def decode_frame(frame: bytes) -> bytes:
        started.set()
        await release.wait()
        return JPEG + frame

    with patch.object(preview, "_decode", side_effect=decode_frame) as decode:
        preview.received(b"first")
        await started.wait()
        preview.received(b"intermediate")
        preview.received(b"latest")
        release.set()
        await hass.async_block_till_done()
        decode.assert_awaited_once_with(b"first")
        assert await preview.image() == JPEG + b"first"
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert decode.await_count == 2
        decode.assert_awaited_with(b"latest")
        assert await preview.image() == JPEG + b"latest"
        await preview.close()


async def test_removal_flushes_latest_frame_and_cancels_delayed_conversion(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    preview = KeypadPreview(hass, "TC-0007-20000001")
    with patch.object(preview, "_decode", side_effect=[JPEG + b"first", JPEG + b"last"]) as decode:
        preview.received(b"first")
        await hass.async_block_till_done()
        preview.received(b"last")
        timer = preview._conversion_timer
        assert timer is not None
        await preview.close()
        assert timer.cancelled()
        assert preview._conversion_timer is None
        decode.assert_awaited_with(b"last")
        restored = KeypadPreview(hass, "TC-0007-20000001")
        await restored.load()
        assert await restored.image() == JPEG + b"last"
        preview.received(b"after-removal")
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert decode.await_count == 2
