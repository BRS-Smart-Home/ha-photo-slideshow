"""Shared base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import SlideshowCoordinator


class SlideshowEntity(CoordinatorEntity[SlideshowCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SlideshowCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)}, name=NAME, manufacturer="BRS", model="Drive photo slideshow",
            entry_type=DeviceEntryType.SERVICE,
        )
