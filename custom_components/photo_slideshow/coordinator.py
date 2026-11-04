"""Coordinator: owns the library, the persistent state and the scheduled jobs (v0.1: library scan)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import library as lib_mod
from . import rules
from .const import (
    CONF_ROOT_FOLDER_ID,
    CONF_SERVICE_ACCOUNT,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_SYNC_FAILED,
    KIND_PHOTO,
    KIND_VIDEO,
    OPT_EXCLUDE_FILES,
    OPT_EXCLUDE_FOLDERS,
    OPT_SCAN_TIME,
    OPT_SCAN_WEEKDAY,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .drive import DriveAuthError, DriveClient, DriveError
from .library import Item
from .state import State

_LOGGER = logging.getLogger(__name__)

ISSUE_DRIVE = "drive_access"


def hm(value: str) -> tuple[int, int]:
    """'HH:MM' or 'HH:MM:SS' -> (hour, minute)."""
    h, m = str(value).split(":")[:2]
    return int(h), int(m)


def _utcnow() -> datetime:
    """Naive UTC time, the form used inside the library and the state."""
    return dt_util.utcnow().replace(tzinfo=None)


class SlideshowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.entry = entry
        self.root_id: str = entry.data[CONF_ROOT_FOLDER_ID]
        self.drive = DriveClient(async_get_clientsession(hass), json.loads(entry.data[CONF_SERVICE_ACCOUNT]))
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.library: dict[str, Item] = {}
        self.state = State()
        self._listing: list[tuple] = []                # (parts, size, duration_ms) of the last scan, for the dry run
        self._lock = asyncio.Lock()
        self._unsubs: list = []

    # ---- options ------------------------------------------------------------------------------
    @property
    def cfg(self) -> dict[str, Any]:
        cfg = {**DEFAULT_OPTIONS, **self.entry.options}
        for key in (OPT_EXCLUDE_FOLDERS, OPT_EXCLUDE_FILES):          # tolerate trailing commas / semicolons typed by hand
            cfg[key] = rules.clean_patterns(cfg[key])
        return cfg

    # ---- persistence --------------------------------------------------------------------------
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.library = {d["id"]: Item.from_dict(d) for d in data.get("library", [])}
        self.state = State.from_dict(data.get("state"))
        self.async_set_updated_data(self.snapshot())

    def _data_to_save(self) -> dict:
        return {"library": [i.to_dict() for i in self.library.values()], "state": self.state.to_dict()}

    def _save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 10)

    # ---- scheduling -----------------------------------------------------------------------------
    @callback
    def async_start(self) -> None:
        h, m = hm(self.cfg[OPT_SCAN_TIME])
        self._unsubs.append(async_track_time_change(self.hass, self._weekly_scan, hour=h, minute=m, second=0))
        if not self.library:                                  # first run: scan right away, in the background
            self.entry.async_create_background_task(self.hass, self.async_scan(), "photo_slideshow_first_scan")

    async def _weekly_scan(self, now: datetime) -> None:
        if dt_util.as_local(now).weekday() == int(self.cfg[OPT_SCAN_WEEKDAY]):
            await self.async_scan()

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data_to_save())
        await super().async_shutdown()

    # ---- the library scan -------------------------------------------------------------------------
    @staticmethod
    def _evaluate_all(files, cfg: dict, now: datetime):
        """Apply the rules to every Drive file (CPU work, runs in the executor)."""
        found: list[Item] = []
        reasons: Counter = Counter()
        listing = []
        for f in files:
            listing.append((f.parts, f.size, f.duration_ms))
            d = rules.evaluate(f.parts, cfg, f.size, f.duration_ms)
            reasons[(d.kind or "other") + ":" + d.reason] += 1
            if d.included:
                found.append(Item(id=f.id, parts=f.parts, kind=d.kind, added=now, size=f.size, modified=f.modified,
                                  duration_ms=f.duration_ms, meta=f.meta))
        return found, reasons, listing

    async def async_scan(self) -> dict:
        """Rescan the Drive folder: update the library, forget hidden items whose file is gone, record statistics."""
        if self._lock.locked():
            raise HomeAssistantError("A scan or sync is already running")
        async with self._lock:
            started = time.monotonic()
            now = _utcnow()
            try:
                files = await self.drive.list_tree(self.root_id)
            except DriveError as err:
                self._scan_failed(err, now)
                if isinstance(err, DriveAuthError):
                    return self.state.last_scan
                raise HomeAssistantError(f"Scan failed: {err}") from err
            found, reasons, listing = await self.hass.async_add_executor_job(self._evaluate_all, files, self.cfg, now)
            self.library, summary = lib_mod.merge_scan(self.library, found, now)
            self._listing = listing
            pruned = self.state.prune_hidden(set(self.library))
            self.state.last_scan = {
                "ok": True, "at": now.isoformat(), "seconds": round(time.monotonic() - started, 1),
                "files_seen": len(files), "included": len(found), "new": summary["new"], "removed": summary["removed"],
                "hidden_pruned": len(pruned), "reasons": dict(reasons), "error": None,
            }
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_DRIVE)
            _LOGGER.info("Scan finished: %s files in Drive, %s in the library (%s new, %s removed)",
                         len(files), len(found), summary["new"], summary["removed"])
            self._save()
            self.async_set_updated_data(self.snapshot())
            return self.state.last_scan

    def _scan_failed(self, err: Exception, now: datetime) -> None:
        _LOGGER.error("Library scan failed: %s", err)
        self.state.last_scan = {**self.state.last_scan, "ok": False, "at": now.isoformat(), "error": str(err)}
        self.state.fails_in_row += 1
        ir.async_create_issue(
            self.hass, DOMAIN, ISSUE_DRIVE, is_fixable=False, severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_DRIVE, translation_placeholders={"error": str(err)},
        )
        self.hass.bus.async_fire(EVENT_SYNC_FAILED, {"stage": "scan", "error": str(err)})
        self._save()
        self.async_set_updated_data(self.snapshot())

    # ---- dry run -------------------------------------------------------------------------------------
    def dry_run(self, overrides: dict | None = None) -> dict:
        """Count what the rules (current, or with overrides) keep or remove, from the last listing. Nothing is changed."""
        cfg = {**self.cfg, **(overrides or {})}
        counts = rules.dry_run(self._listing, cfg)
        return {"files_in_listing": len(self._listing), "counts": dict(sorted(counts.items()))}

    # ---- numbers for the entities ----------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        photos = sum(1 for i in self.library.values() if i.kind == KIND_PHOTO)
        videos = sum(1 for i in self.library.values() if i.kind == KIND_VIDEO)
        ls = self.state.last_scan or {}
        return {
            "photos": photos, "videos": videos,
            "files_seen": ls.get("files_seen"), "included": ls.get("included"),
            "excluded": (ls["files_seen"] - ls["included"]) if ls.get("files_seen") is not None and ls.get("included") is not None else None,
            "new": ls.get("new"), "hidden": len(self.state.hidden),
            "last_scan_at": ls.get("at"), "last_scan_ok": ls.get("ok"), "last_scan_error": ls.get("error"),
            "last_scan": ls,
            "likes": self.state.totals.get("like", 0), "likes_pending": len(self.state.pending["like"]),
            "fixes": self.state.totals.get("fix", 0), "fixes_pending": len(self.state.pending["fix"]),
            "hidden_pending": len(self.state.pending["hide"]),
            "shown_photo": len(self.state.used[KIND_PHOTO]), "shown_video": len(self.state.used[KIND_VIDEO]),
            "progress_photo": self.state.progress(KIND_PHOTO, photos),
            "progress_video": self.state.progress(KIND_VIDEO, videos),
            "cycle_photo": self.state.cycles[KIND_PHOTO], "cycle_video": self.state.cycles[KIND_VIDEO],
        }
