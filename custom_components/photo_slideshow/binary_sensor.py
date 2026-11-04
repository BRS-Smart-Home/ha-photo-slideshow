"""Problem sensor: the last scan failed, or there has been no successful scan for too long."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .entity import SlideshowEntity

STALE_AFTER = timedelta(days=10)          # a weekly scan is overdue after 10 days


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ScanProblem(entry.runtime_data)])


class ScanProblem(SlideshowEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "scan_problem")

    @property
    def is_on(self) -> bool:
        d = self.coordinator.data
        if d.get("last_scan_ok") is False:
            return True
        at = d.get("last_scan_at")
        if not at:
            return False                      # nothing scanned yet is not a problem (the first scan is starting)
        return dt_util.utcnow() - datetime.fromisoformat(at).replace(tzinfo=timezone.utc) > STALE_AFTER

    @property
    def extra_state_attributes(self):
        err = self.coordinator.data.get("last_scan_error")
        return {"error": err} if err else None
