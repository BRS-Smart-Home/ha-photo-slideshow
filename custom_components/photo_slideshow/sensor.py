"""Sensors: library size, scan statistics, cycle progress."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import SlideshowEntity


@dataclass(frozen=True, kw_only=True)
class SlideshowSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc) if value else None


SENSORS: tuple[SlideshowSensorDescription, ...] = (
    SlideshowSensorDescription(key="library_photos", translation_key="library_photos", icon="mdi:image-multiple",
                               state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d["photos"]),
    SlideshowSensorDescription(key="library_videos", translation_key="library_videos", icon="mdi:movie-open",
                               state_class=SensorStateClass.MEASUREMENT, value_fn=lambda d: d["videos"]),
    SlideshowSensorDescription(key="files_seen", translation_key="files_seen", icon="mdi:google-drive",
                               entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda d: d["files_seen"]),
    SlideshowSensorDescription(key="excluded", translation_key="excluded", icon="mdi:filter-remove",
                               entity_category=EntityCategory.DIAGNOSTIC, value_fn=lambda d: d["excluded"],
                               attrs_fn=lambda d: {"by_rule": (d.get("last_scan") or {}).get("reasons", {})}),
    SlideshowSensorDescription(key="new_last_scan", translation_key="new_last_scan", icon="mdi:new-box",
                               value_fn=lambda d: d["new"]),
    SlideshowSensorDescription(key="hidden", translation_key="hidden", icon="mdi:eye-off",
                               value_fn=lambda d: d["hidden"], attrs_fn=lambda d: {"pending_in_report": d["hidden_pending"]}),
    SlideshowSensorDescription(key="likes", translation_key="likes", icon="mdi:heart", state_class=SensorStateClass.TOTAL_INCREASING,
                               value_fn=lambda d: d["likes"], attrs_fn=lambda d: {"pending_in_report": d["likes_pending"]}),
    SlideshowSensorDescription(key="fixes", translation_key="fixes", icon="mdi:wrench", state_class=SensorStateClass.TOTAL_INCREASING,
                               value_fn=lambda d: d["fixes"], attrs_fn=lambda d: {"pending_in_report": d["fixes_pending"]}),
    SlideshowSensorDescription(key="shown_photo", translation_key="shown_photo", icon="mdi:image-check",
                               value_fn=lambda d: d["shown_photo"]),
    SlideshowSensorDescription(key="shown_video", translation_key="shown_video", icon="mdi:movie-check",
                               value_fn=lambda d: d["shown_video"]),
    SlideshowSensorDescription(key="last_scan", translation_key="last_scan", device_class=SensorDeviceClass.TIMESTAMP,
                               value_fn=lambda d: _ts(d["last_scan_at"]),
                               attrs_fn=lambda d: {k: v for k, v in (d.get("last_scan") or {}).items() if k not in ("reasons", "at")}),
    SlideshowSensorDescription(key="last_sync", translation_key="last_sync", device_class=SensorDeviceClass.TIMESTAMP,
                               value_fn=lambda d: _ts(d["last_sync_at"]),
                               attrs_fn=lambda d: {k: v for k, v in (d.get("last_sync") or {}).items() if k != "at"}),
    SlideshowSensorDescription(key="today", translation_key="today", icon="mdi:calendar-today",
                               value_fn=lambda d: d["today"]),
    SlideshowSensorDescription(key="cycle_photo", translation_key="cycle_photo", icon="mdi:progress-clock",
                               native_unit_of_measurement=PERCENTAGE, value_fn=lambda d: d["progress_photo"],
                               attrs_fn=lambda d: {"cycle": d["cycle_photo"]}),
    SlideshowSensorDescription(key="cycle_video", translation_key="cycle_video", icon="mdi:progress-clock",
                               native_unit_of_measurement=PERCENTAGE, value_fn=lambda d: d["progress_video"],
                               attrs_fn=lambda d: {"cycle": d["cycle_video"]}),
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SlideshowSensor(coordinator, d) for d in SENSORS)


class SlideshowSensor(SlideshowEntity, SensorEntity):
    entity_description: SlideshowSensorDescription

    def __init__(self, coordinator, description: SlideshowSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None
