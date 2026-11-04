"""Buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import SlideshowEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ScanNowButton(entry.runtime_data), SyncNowButton(entry.runtime_data), SendReportButton(entry.runtime_data)])


class ScanNowButton(SlideshowEntity, ButtonEntity):
    _attr_icon = "mdi:folder-search"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "scan_now")

    async def async_press(self) -> None:
        await self.coordinator.async_scan()


class SyncNowButton(SlideshowEntity, ButtonEntity):
    _attr_icon = "mdi:image-sync"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sync_now")

    async def async_press(self) -> None:
        await self.coordinator.async_sync()


class SendReportButton(SlideshowEntity, ButtonEntity):
    """Send the report now, on top of the daily schedule (marks since the last report; they are cleared once it is sent)."""
    _attr_icon = "mdi:email-fast"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "send_report_now")

    async def async_press(self) -> None:
        result = await self.coordinator.async_send_report()
        if not result.get("sent"):
            raise HomeAssistantError(f"Report not sent: {result.get('reason', 'unknown reason')}")
