from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MyQDataUpdateCoordinator
from .entity import MyQEntity
from .models import GarageDoor
from .runtime import MyQConfigEntry

type IsOnFn = Callable[[GarageDoor], bool | None]
type ExistsFn = Callable[[GarageDoor], bool]


@dataclass(frozen=True, kw_only=True)
class MyQBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Select a door flag and the devices that expose it."""

    is_on_fn: IsOnFn
    exists_fn: ExistsFn


BINARY_SENSOR_DESCRIPTIONS: tuple[MyQBinarySensorEntityDescription, ...] = (
    MyQBinarySensorEntityDescription(
        key="door_open",
        translation_key="door_open",
        device_class=BinarySensorDeviceClass.GARAGE_DOOR,
        is_on_fn=lambda door: door.is_open,
        exists_fn=lambda door: True,
    ),
    MyQBinarySensorEntityDescription(
        key="vacation_mode",
        translation_key="vacation_mode",
        icon="mdi:beach",
        is_on_fn=lambda door: door.in_vacation_mode,
        exists_fn=lambda door: door.in_vacation_mode is not None,
    ),
    MyQBinarySensorEntityDescription(
        key="work_light",
        translation_key="work_light",
        icon="mdi:lightbulb",
        is_on_fn=lambda door: door.attached_worklight_on,
        exists_fn=lambda door: door.attached_worklight_on is not None,
    ),
    MyQBinarySensorEntityDescription(
        key="active_fault",
        translation_key="active_fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda door: bool(door.active_fault_codes),
        exists_fn=lambda door: True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MyQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register door flags supported by the discovered devices."""
    del hass
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MyQBinarySensor(coordinator, door, description)
        for door in coordinator.data.values()
        for description in BINARY_SENSOR_DESCRIPTIONS
        if description.exists_fn(door)
    )


class MyQBinarySensor(MyQEntity, BinarySensorEntity):
    """Expose a discovered door flag without additional cloud requests."""

    entity_description: MyQBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: MyQDataUpdateCoordinator,
        door: GarageDoor,
        description: MyQBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, door)
        self.entity_description = description
        self._attr_unique_id = f"{door.serial_number}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Read the current flag from the coordinator discovery result."""
        door = self.door
        if door is None:
            return None
        return self.entity_description.is_on_fn(door)

    @property
    def extra_state_attributes(self) -> dict[str, tuple[str, ...]] | None:
        """Attach reported fault codes only to the active-fault entity."""
        door = self.door
        if (
            self.entity_description.key != "active_fault"
            or door is None
            or not door.active_fault_codes
        ):
            return None
        return {"fault_codes": door.active_fault_codes}
