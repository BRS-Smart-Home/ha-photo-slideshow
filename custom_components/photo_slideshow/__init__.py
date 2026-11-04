"""Travel Slideshow: keeps a travel photo / video slideshow fed from Google Drive (read-only)."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import SlideshowCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

type SlideshowConfigEntry = ConfigEntry[SlideshowCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_DRY_RUN = "dry_run"
SERVICE_SCAN = "scan"
DRY_RUN_SCHEMA = vol.Schema({
    vol.Optional("exclude_folders"): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("exclude_files"): vol.All(cv.ensure_list, [cv.string]),
})


def _coordinator(hass: HomeAssistant) -> SlideshowCoordinator:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if getattr(e, "runtime_data", None)]
    if not entries:
        raise HomeAssistantError("Travel Slideshow is not set up")
    return entries[0].runtime_data


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def handle_dry_run(call: ServiceCall) -> ServiceResponse:
        return _coordinator(hass).dry_run({k: v for k, v in call.data.items()})

    async def handle_scan(call: ServiceCall) -> ServiceResponse:
        return await _coordinator(hass).async_scan()

    hass.services.async_register(DOMAIN, SERVICE_DRY_RUN, handle_dry_run, schema=DRY_RUN_SCHEMA,
                                 supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, SERVICE_SCAN, handle_scan, supports_response=SupportsResponse.OPTIONAL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SlideshowConfigEntry) -> bool:
    coordinator = SlideshowCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    coordinator.async_start()
    return True


async def _options_updated(hass: HomeAssistant, entry: SlideshowConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SlideshowConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_shutdown()
    return ok
