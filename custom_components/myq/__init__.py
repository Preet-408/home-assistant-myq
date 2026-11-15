from collections.abc import Mapping
from typing import cast

from aiohttp import ClientError
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import MyQClient
from .const import CONF_CAMERA_LAN_ONLY, CONF_TOKENS, DOMAIN
from .coordinator import MyQDataUpdateCoordinator
from .exceptions import MyQApiError, MyQAuthenticationError
from .keypad_preview import KeypadPreview
from .models import OAuthTokens
from .oauth import MyQAuth
from .runtime import (
    MyQConfigData,
    MyQConfigEntry,
    MyQRuntimeData,
    tokens_from_data,
    tokens_to_data,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS: tuple[Platform, ...] = (
    Platform.BINARY_SENSOR,
    Platform.CAMERA,
    Platform.COVER,
    Platform.SENSOR,
)


async def async_setup_entry(hass: HomeAssistant, entry: MyQConfigEntry) -> bool:
    data = cast(MyQConfigData, entry.data)

    @callback
    def async_store_tokens(tokens: OAuthTokens) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_TOKENS: tokens_to_data(tokens)},
        )

    try:
        token_data = cast(Mapping[str, object], data[CONF_TOKENS])
        auth = MyQAuth(
            async_get_clientsession(hass),
            tokens_from_data(token_data),
            async_store_tokens,
        )
        client = MyQClient(async_get_clientsession(hass), auth)
        coordinator = MyQDataUpdateCoordinator(hass, entry, client)
        await coordinator.async_config_entry_first_refresh()
    except MyQAuthenticationError as error:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="invalid_auth",
        ) from error
    except ClientError as error:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
        ) from error
    except (MyQApiError, ValueError) as error:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="api_error",
        ) from error

    serials = set(entry.data.get("preview_serials", ()))
    serials.update(
        camera.serial_number for camera in coordinator.cameras.values() if camera.is_video_keypad
    )
    serials.update(
        door.camera.serial_number
        for door in coordinator.data.values()
        if door.camera and door.camera.is_video_keypad
    )
    if serials != set(entry.data.get("preview_serials", ())):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "preview_serials": sorted(serials)}
        )

    current_lan_only = entry.options.get(CONF_CAMERA_LAN_ONLY, False)

    async def camera_policy_changed(hass: HomeAssistant, updated: MyQConfigEntry) -> None:
        # Data-only updates (including OAuth refresh) must not interrupt live video.
        nonlocal current_lan_only
        policy = updated.options.get(CONF_CAMERA_LAN_ONLY, False)
        if policy != current_lan_only:
            current_lan_only = policy
            await hass.config_entries.async_reload(updated.entry_id)

    entry.async_on_unload(entry.add_update_listener(camera_policy_changed))
    entry.runtime_data = MyQRuntimeData(client=client, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MyQConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: MyQConfigEntry) -> None:
    """Erase this entry's previews, including devices missing at its last setup."""
    serials = set(entry.data.get("preview_serials", ()))
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        serials.update(serial for domain, serial in device.identifiers if domain == DOMAIN)
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id != entry.entry_id:
            serials.difference_update(other.data.get("preview_serials", ()))
            for device in dr.async_entries_for_config_entry(registry, other.entry_id):
                serials.difference_update(
                    serial for domain, serial in device.identifiers if domain == DOMAIN
                )
    for serial in serials:
        await KeypadPreview(hass, serial).remove()
