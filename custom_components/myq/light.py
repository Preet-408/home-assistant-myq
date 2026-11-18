from collections.abc import Awaitable, Callable
from typing import Literal

from aiohttp import ClientError
from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MyQDataUpdateCoordinator
from .entity import myq_device_info
from .exceptions import MyQApiError, MyQError
from .models import MyQLight
from .runtime import MyQConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register each discovered standalone light control."""
    del hass
    coordinator = entry.runtime_data.coordinator
    async_add_entities(MyQLightEntity(coordinator, light) for light in coordinator.lights.values())


class MyQLightEntity(CoordinatorEntity[MyQDataUpdateCoordinator], LightEntity):
    """Expose a standalone light's reported state and on/off commands."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator: MyQDataUpdateCoordinator, light: MyQLight) -> None:
        super().__init__(coordinator)
        self._attr_supported_color_modes = {ColorMode.ONOFF}
        self._serial_number = light.serial_number
        self._attr_unique_id = light.serial_number
        self._attr_device_info = myq_device_info(
            light.serial_number, name=light.name, model=light.device_model
        )

    @property
    def available(self) -> bool:
        """Require successful discovery and a light that is not reported offline."""
        light = self.coordinator.lights.get(self._serial_number)
        return super().available and light is not None and light.online is not False

    @property
    def is_on(self) -> bool | None:
        """Read power from the latest device report."""
        light = self.coordinator.lights.get(self._serial_number)
        return light.is_on if light is not None else None

    async def async_turn_on(self, **kwargs: object) -> None:
        """Request power on and poll for the reported result."""
        del kwargs
        await self._async_command(self.coordinator.client.async_turn_on_light, "on")

    async def async_turn_off(self, **kwargs: object) -> None:
        """Request power off and poll for the reported result."""
        del kwargs
        await self._async_command(self.coordinator.client.async_turn_off_light, "off")

    async def _async_command(
        self, command: Callable[[MyQLight], Awaitable[None]], target: Literal["on", "off"]
    ) -> None:
        try:
            light = self.coordinator.lights.get(self._serial_number)
            if light is None or not self.available:
                raise MyQApiError("The light control is unavailable")
            await command(light)
        except (ClientError, MyQError, TimeoutError) as error:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="command_failed"
            ) from error
        self.coordinator.async_schedule_command_updates(light.serial_number, target)
