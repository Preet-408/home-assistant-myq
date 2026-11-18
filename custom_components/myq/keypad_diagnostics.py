"""Account-scoped keypad diagnostics, cached power and passive preview timestamps."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .exceptions import MyQApiError
from .keypad_state import POWER_MAX_AGE, KeypadPower, KeypadState
from .models import MyQCamera

_POWER_REFRESH_INTERVAL = 60


class KeypadDiagnostics:
    """Own cached keypad readings and their lifecycle independently of device polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        keypads: Callable[[], tuple[MyQCamera, ...]],
        read_power: Callable[[MyQCamera], Awaitable[KeypadPower]],
        on_change: Callable[[], None],
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._keypads = keypads
        self._read_power = read_power
        self._on_change = on_change
        self._states: dict[str, KeypadState] = {}
        self._snapshot_times: dict[str, datetime] = {}
        self._credential_renewals = 0
        self._power_expiry: dict[str, asyncio.TimerHandle] = {}
        self._power_request: asyncio.Task[KeypadPower] | None = None
        self._closed = False
        self._power_lock = asyncio.Lock()
        self._power_data: dict[str, object] = {}
        self._store = Store[dict[str, object]](
            hass, 1, f"{DOMAIN}.{entry_id}.keypads", private=True
        )

    def state(self, serial: str) -> KeypadState:
        """Return the local diagnostics for one keypad without requesting metadata."""
        if serial not in self._states:
            self._states[serial] = KeypadState(credential_renewals=self._credential_renewals)
        return self._states[serial]

    def snapshot_signal(self, serial: str) -> str:
        """Address preview updates to the timestamp sensor for this entry and keypad."""
        return f"{DOMAIN}_{self._entry_id}_{serial}_snapshot"

    def snapshot_time(self, serial: str) -> datetime | None:
        """Return the capture time of the cached preview."""
        return self._snapshot_times.get(serial)

    @callback
    def async_set_snapshot_time(self, serial: str, at: datetime | None) -> None:
        """Publish a locally captured preview time without requesting device data."""
        if at is not None:
            self._snapshot_times[serial] = at
            async_dispatcher_send(self._hass, self.snapshot_signal(serial))

    @callback
    def async_stream_event(self, serial: str, event: str, value: str | int | float | None) -> None:
        """Record a shared video session event and notify diagnostic entities."""
        self.state(serial).stream_event(event, value)
        self._on_change()

    @callback
    def async_token_refreshed(self) -> None:
        """Record an account credential renewal in each keypad's diagnostics."""
        self._credential_renewals += 1
        for state in self._states.values():
            state.credential_renewals = self._credential_renewals
        self._on_change()

    async def async_load(self) -> None:
        """Restore cached power samples with their original expiry times."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        self._power_data = stored
        for camera in self._keypads():
            data = stored.get(camera.serial_number)
            if (
                isinstance(data, dict)
                and isinstance(power := data.get("power"), dict)
                and (sample := KeypadPower.from_storage(power))
            ):
                self._set_power(camera.serial_number, sample)

    def _set_power(self, serial: str, power: KeypadPower) -> None:
        self.state(serial).power = power
        if previous := self._power_expiry.pop(serial, None):
            previous.cancel()
        delay = power.sampled_at + POWER_MAX_AGE - time.time()
        if delay > 0:
            self._power_expiry[serial] = self._hass.loop.call_later(
                delay, self._expire_power, serial
            )

    @callback
    def _expire_power(self, serial: str) -> None:
        self._power_expiry.pop(serial, None)
        self._on_change()

    async def async_refresh_power(self, serial: str) -> None:
        """Share explicit refreshes and preserve other cached metadata when updating power."""
        async with self._power_lock:
            if self._closed:
                raise MyQApiError("Keypad diagnostics have shut down")
            camera = next((item for item in self._keypads() if item.serial_number == serial), None)
            if camera is None:
                raise MyQApiError("Keypad is no longer present")
            state = self.state(serial)
            if state.power and 0 <= time.time() - state.power.sampled_at < _POWER_REFRESH_INTERVAL:
                return

            async def request_power() -> KeypadPower:
                return await self._read_power(camera)

            self._power_request = self._hass.async_create_task(request_power())
            try:
                power = await self._power_request
            finally:
                self._power_request = None
            if bool(self._closed):
                return
            previous = self._power_data.get(serial)
            metadata = previous.copy() if isinstance(previous, dict) else {}
            metadata["power"] = power.as_dict()
            updated = {**self._power_data, serial: metadata}
            await self._store.async_save(updated)
            if bool(self._closed):
                return
            self._power_data = updated
            self._set_power(serial, power)
            self._on_change()

    async def async_shutdown(self) -> None:
        """Cancel power requests, drain storage writes and release expiry timers."""
        self._closed = True
        if self._power_request is not None:
            self._power_request.cancel()
        async with self._power_lock:
            pass
        for timer in self._power_expiry.values():
            timer.cancel()
        self._power_expiry.clear()
