"""Share camera preparation failures without repeating cloud wake requests."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientSession

from custom_components.myq.client import MyQClient
from custom_components.myq.exceptions import MyQApiError, MyQRateLimitError, MyQWakeTimeoutError
from custom_components.myq.models import MyQCamera
from custom_components.myq.oauth import MyQAuth
from custom_components.myq.tend_protocol import TendCameraTarget, TendStreamError
from custom_components.myq.tend_stream import TendLiveStream

from .http import FakeResponse, FakeSession

TARGET = TendCameraTarget(destination="account:camera")


async def test_concurrent_viewers_share_failed_wake_and_retry_only_after_delay() -> None:
    session = FakeSession(
        request_responses=[
            FakeResponse("", status=503, body="unavailable"),
            FakeResponse("", body="{}"),
            FakeResponse(
                "",
                body='{"id":"20000001","alias":"account:camera","status":{"pwr":{"sleepMode":"FP"}}}',
            ),
        ]
    )
    auth = MagicMock(spec=MyQAuth)
    auth.async_access_token = AsyncMock(return_value="synthetic-token")
    client = MyQClient(cast(ClientSession, session), auth)
    keypad = MyQCamera("TC-0007-20000001", True, "vkp-camera")

    async def prepare() -> TendCameraTarget:
        alias = await client.async_prepare_keypad(keypad)
        assert alias is not None
        return TendCameraTarget(destination=alias)

    stream = TendLiveStream(prepare, auth.async_access_token)
    try:
        with (
            patch("custom_components.myq.tend_stream.monotonic", return_value=100) as clock,
            patch("custom_components.myq.tend_stream.TendSession.open") as opened,
        ):
            opened.return_value = MagicMock(ended=False, close=AsyncMock())
            results = await asyncio.gather(
                *(stream._subscribe() for _ in range(3)), return_exceptions=True
            )
            assert all(isinstance(result, TendStreamError) for result in results)
            assert len({str(result) for result in results}) == 1
            assert len(session.calls) == 1
            assert session.calls[0].method == "POST"
            opened.assert_not_awaited()
            clock.return_value = 129
            with pytest.raises(TendStreamError):
                await stream._subscribe()
            assert len(session.calls) == 1
            clock.return_value = 130
            await asyncio.gather(stream._subscribe(), stream._subscribe())
            assert [call.method for call in session.calls] == ["POST", "POST", "GET"]
            opened.assert_awaited_once()
    finally:
        await stream.close()


@pytest.mark.parametrize(
    ("failure", "delay"),
    [
        (MyQApiError("private"), 30),
        (MyQWakeTimeoutError("private"), 30),
        (MyQRateLimitError(90), 90),
    ],
)
async def test_preparation_pause_survives_idle_cleanup_and_resets_after_success(
    failure: Exception, delay: int
) -> None:
    prepare = AsyncMock(side_effect=[failure, TARGET, TARGET])
    stream = TendLiveStream(prepare, AsyncMock(return_value="synthetic-token"))
    try:
        with (
            patch("custom_components.myq.tend_stream.monotonic", return_value=100) as clock,
            patch("custom_components.myq.tend_stream.TendSession.open") as opened,
        ):
            opened.return_value = MagicMock(ended=False, close=AsyncMock())
            with pytest.raises(TendStreamError) as result:
                await stream._subscribe()
            assert "private" not in str(result.value)
            await stream._close_if_idle()
            clock.return_value = 100 + delay - 1
            with pytest.raises(TendStreamError):
                await stream._subscribe()
            prepare.assert_awaited_once()
            clock.return_value += 1
            await stream._subscribe()
            assert prepare.await_count == 2
            opened.return_value.ended = True
            await stream._subscribe()
            assert prepare.await_count == 3
    finally:
        await stream.close()
