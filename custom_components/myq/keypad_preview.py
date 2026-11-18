"""A passive, persistent preview built only from already received keypad video."""

from __future__ import annotations

import asyncio
import base64
import binascii
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic

from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_setup_component

_MAX_FRAME = 3_000_000
_CONVERSION_INTERVAL = 30.0
_SAVE_DELAY = 30


class KeypadPreview:
    """Keep a bounded keyframe; viewing the preview never starts a camera session."""

    def __init__(
        self, hass: HomeAssistant, camera_serial: str, on_update: Callable[[], None] | None = None
    ) -> None:
        self.hass = hass
        self._store = Store[dict[str, str | float]](
            hass, 1, f"myq.{camera_serial}.preview", private=True
        )
        self._on_update = on_update
        self._pending: tuple[bytes, float] | None = None
        self._conversion: asyncio.Task[None] | None = None
        self._conversion_timer: asyncio.TimerHandle | None = None
        self._next_conversion_at = 0.0
        self._closed = False
        self._frame_at: float | None = None
        self._image: bytes | None = None

    @property
    def captured_at(self) -> datetime | None:
        """Return the capture time belonging to the last successfully decoded image."""
        return datetime.fromtimestamp(self._frame_at, UTC) if self._frame_at else None

    def received(self, frame: bytes) -> None:
        """Queue a bounded live keyframe for shared local conversion."""
        if self._closed or not frame or len(frame) > _MAX_FRAME:
            return
        self._pending = (frame, time.time())
        self._schedule_conversion()

    def _schedule_conversion(self) -> None:
        if (
            self._closed
            or self._pending is None
            or self._conversion_timer is not None
            or (self._conversion is not None and not self._conversion.done())
        ):
            return
        delay = self._next_conversion_at - monotonic()
        if delay > 0:
            self._conversion_timer = self.hass.loop.call_later(delay, self._start_conversion)
        else:
            self._start_conversion()

    def _start_conversion(self) -> None:
        self._conversion_timer = None
        self._conversion = self.hass.async_create_task(self._convert_pending())

    async def _convert_pending(self) -> None:
        assert self._pending is not None
        frame, at = self._pending
        self._pending = None
        self._next_conversion_at = monotonic() + _CONVERSION_INTERVAL
        try:
            try:
                image = await self._decode(frame)
            except OSError, TimeoutError:
                return
            if image is not None:
                self._image, self._frame_at = image, at
                self._store.async_delay_save(self._data, _SAVE_DELAY)
                if self._on_update:
                    self._on_update()
        finally:
            self._conversion = None
            self._schedule_conversion()

    def _data(self) -> dict[str, str | float]:
        if self._image is None or self._frame_at is None:
            return {}
        return {"jpeg": base64.b64encode(self._image).decode("ascii"), "at": self._frame_at}

    async def load(self) -> None:
        """Restore a validated preview and its original capture time from storage."""
        stored: object = await self._store.async_load() or {}
        if not isinstance(stored, dict):
            return
        frame, at = stored.get("jpeg", stored.get("frame")), stored.get("at")
        if (
            not isinstance(frame, str)
            or len(frame) > _MAX_FRAME * 4 // 3
            or not isinstance(at, (int, float))
            or isinstance(at, bool)
            or not math.isfinite(at)
            or not 0 < at <= time.time() + 300
        ):
            return
        try:
            decoded = base64.b64decode(frame, validate=True)
        except ValueError, binascii.Error:
            return
        if not decoded or len(decoded) > _MAX_FRAME:
            return
        if "jpeg" in stored:
            image = decoded if decoded.startswith(b"\xff\xd8") else None
        else:
            # Older stores contain a raw H.264 keyframe.
            try:
                image = await self._decode(decoded)
            except OSError, TimeoutError:
                return
        if image is not None:
            self._image, self._frame_at = image, float(at)

    async def close(self) -> None:
        """Stop sampling and persist the newest pending frame before removal."""
        self._closed = True
        if self._conversion_timer is not None:
            self._conversion_timer.cancel()
            self._conversion_timer = None
        if self._conversion is not None:
            await self._conversion
        if self._pending is not None:
            await self._convert_pending()
        if self._image is not None:
            await self._store.async_save(self._data())

    async def image(self) -> bytes | None:
        """Return the cached JPEG without subscribing to live video."""
        if self._image is None and self._conversion is not None:
            await asyncio.shield(self._conversion)
        return self._image

    async def _decode(self, frame: bytes) -> bytes | None:
        if not await async_setup_component(self.hass, "ffmpeg", {}):
            return None
        process = await asyncio.create_subprocess_exec(
            get_ffmpeg_manager(self.hass).binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-f",
            "h264",
            "-i",
            "pipe:0",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(10):
                image, _ = await process.communicate(frame)
            if (
                process.returncode == 0
                and len(image) <= _MAX_FRAME
                and image.startswith(b"\xff\xd8")
            ):
                return image
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        return None

    async def remove(self) -> None:
        """Delete the private preview file for this camera."""
        await self._store.async_remove()
