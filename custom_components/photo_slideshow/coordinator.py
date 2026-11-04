"""Coordinator: owns the library, the persistent state and the scheduled jobs (v0.1: library scan)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
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
from . import media, rules
from . import sync as sync_mod
from .const import (
    CONF_OUTPUT_DIR,
    CONF_ROOT_FOLDER_ID,
    CONF_SERVICE_ACCOUNT,
    DEFAULT_OPTIONS,
    DOMAIN,
    EVENT_REPORT_SENT,
    EVENT_SYNC_FAILED,
    KIND_PHOTO,
    KIND_VIDEO,
    MARK_LIKE,
    MARKS,
    OPT_EXCLUDE_FILES,
    OPT_EXCLUDE_FOLDERS,
    OPT_FAILS_BEFORE_PUSH,
    OPT_MAX_VIDEO_MB,
    OPT_MAX_VIDEO_SECONDS,
    OPT_PHOTOS_PER_DAY,
    OPT_REPORT_NOTIFY,
    OPT_REPORT_TIME,
    OPT_SCAN_TIME,
    OPT_SCAN_WEEKDAY,
    OPT_SYNC_TIME,
    OPT_VIDEOS_PER_DAY,
    SAFETY_MAX_PHOTO_PX,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .drive import DriveAuthError, DriveClient, DriveError
from .library import Item
from .manifest_out import build_legacy_manifest, build_manifest, local_name
from .report import build_report
from .state import State

_LOGGER = logging.getLogger(__name__)

ISSUE_DRIVE = "drive_access"
ISSUE_SYNC = "sync_failed"


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
        sh, sm = hm(self.cfg[OPT_SYNC_TIME])
        self._unsubs.append(async_track_time_change(self.hass, self._daily_sync, hour=sh, minute=sm, second=0))
        rh, rm = hm(self.cfg[OPT_REPORT_TIME])
        self._unsubs.append(async_track_time_change(self.hass, self._daily_report, hour=rh, minute=rm, second=0))
        if not self.library:                                  # first run: scan right away, in the background
            self.entry.async_create_background_task(self.hass, self.async_scan(), "photo_slideshow_first_scan")

    async def _weekly_scan(self, now: datetime) -> None:
        if dt_util.as_local(now).weekday() == int(self.cfg[OPT_SCAN_WEEKDAY]):
            await self.async_scan()

    async def _daily_sync(self, now: datetime) -> None:
        try:
            await self.async_sync()
        except HomeAssistantError as err:                    # already logged and reported by async_sync
            _LOGGER.warning("Daily sync did not run: %s", err)

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

    # ---- the daily sync --------------------------------------------------------------------------------
    @staticmethod
    def _prepare_dir(path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)

    @staticmethod
    def _write_manifests(stage: Path, files: list) -> None:
        (stage / "manifest.json").write_text(json.dumps(build_manifest(files), ensure_ascii=False, indent=1), encoding="utf-8")
        (stage / "manifest.txt").write_text(build_legacy_manifest(files), encoding="utf-8")

    @staticmethod
    def _swap_dirs(stage: Path, out: Path) -> None:
        """Publish the new folder: the old one is moved away and removed only after the new one is in place."""
        old = out.with_name(f".{out.name}_old")
        shutil.rmtree(old, ignore_errors=True)
        if out.exists():
            out.rename(old)
        stage.rename(out)
        shutil.rmtree(old, ignore_errors=True)

    async def async_sync(self) -> dict:
        """Build today's slideshow in the output folder. Failed items are replaced; 'used' is recorded only on success."""
        if self._lock.locked():
            raise HomeAssistantError("A scan or sync is already running")
        async with self._lock:
            started = time.monotonic()
            now = _utcnow()
            cfg = self.cfg
            out = Path(self.entry.data[CONF_OUTPUT_DIR])
            stage = out.with_name(f".{out.name}_new")
            targets = {KIND_PHOTO: int(cfg[OPT_PHOTOS_PER_DAY]), KIND_VIDEO: int(cfg[OPT_VIDEOS_PER_DAY])}
            try:
                if not self.library:
                    raise DriveError("The library is empty; run a scan first")
                await self.hass.async_add_executor_job(self._prepare_dir, stage)

                async def fetch(item: Item, counter: int) -> str:
                    ext = rules.ext_of(item.name)
                    tmp = stage / f".download_{counter}"
                    try:
                        if item.kind == KIND_PHOTO:
                            fname = local_name(counter, item.parts, sync_mod.photo_target_ext(ext))
                            await self.drive.download_to(item.id, tmp, max_bytes=500 * 1024 * 1024)
                            await self.hass.async_add_executor_job(media.convert_photo, tmp, stage / fname, SAFETY_MAX_PHOTO_PX)
                        else:
                            fname = local_name(counter, item.parts, "mp4")
                            await self.drive.download_to(item.id, tmp, max_bytes=2000 * 1024 * 1024)
                            await media.convert_video(tmp, stage / fname, int(cfg[OPT_MAX_VIDEO_SECONDS]), int(cfg[OPT_MAX_VIDEO_MB]))
                        return fname
                    finally:
                        await self.hass.async_add_executor_job(lambda: tmp.unlink(missing_ok=True))

                res = await sync_mod.build_day(self.library, self.state.used, self.state.hidden_ids(), targets, fetch)
                ok, why = sync_mod.day_is_acceptable(res, targets)
                if not ok:
                    raise DriveError(why)
                await self.hass.async_add_executor_job(self._write_manifests, stage, res.done)
                await self.hass.async_add_executor_job(self._swap_dirs, stage, out)
            except (DriveError, OSError, RuntimeError) as err:
                await self.hass.async_add_executor_job(lambda: shutil.rmtree(stage, ignore_errors=True))
                await self._sync_failed(err, now)
                raise HomeAssistantError(f"Sync failed: {err}") from err

            for kind, ids, reset in sync_mod.used_ids_to_record(res):
                self.state.mark_used(kind, ids, cycle_reset=reset)
            self.state.totals["shown"] = self.state.totals.get("shown", 0) + len(res.done)
            self.state.today = [it.id for it, _ in res.done]
            self.state.fails_in_row = 0
            self.state.last_sync = {
                "ok": True, "at": now.isoformat(), "seconds": round(time.monotonic() - started, 1),
                "photos": len(res.ids[KIND_PHOTO]), "videos": len(res.ids[KIND_VIDEO]),
                "short_photos": res.short[KIND_PHOTO], "short_videos": res.short[KIND_VIDEO],
                "failed": res.failed[:20], "failed_count": len(res.failed), "error": None,
            }
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_SYNC)
            _LOGGER.info("Sync finished: %s photos, %s videos, %s items failed and were replaced",
                         len(res.ids[KIND_PHOTO]), len(res.ids[KIND_VIDEO]), len(res.failed))
            self._save()
            self.async_set_updated_data(self.snapshot())
            return self.state.last_sync

    async def _sync_failed(self, err: Exception, now: datetime) -> None:
        _LOGGER.error("Sync failed: %s", err)
        self.state.fails_in_row += 1
        self.state.last_sync = {**self.state.last_sync, "ok": False, "at": now.isoformat(), "error": str(err)}
        ir.async_create_issue(
            self.hass, DOMAIN, ISSUE_SYNC, is_fixable=False, severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_SYNC, translation_placeholders={"error": str(err)},
        )
        self.hass.bus.async_fire(EVENT_SYNC_FAILED, {"stage": "sync", "error": str(err), "in_a_row": self.state.fails_in_row})
        if self.state.fails_in_row >= int(self.cfg[OPT_FAILS_BEFORE_PUSH]):
            await self._push(f"Travel Slideshow: {self.state.fails_in_row} syncs failed in a row. Last error: {err}")
        self._save()
        self.async_set_updated_data(self.snapshot())

    async def _push(self, message: str) -> None:
        """Send to the configured notify services (entries that are plain e-mail addresses belong to the report, not here)."""
        for target in self.cfg[OPT_REPORT_NOTIFY]:
            if not str(target).startswith("notify."):
                continue
            domain, service = str(target).split(".", 1)
            try:
                await self.hass.services.async_call(domain, service, {"title": "Travel Slideshow", "message": message}, blocking=True)
            except Exception as err:  # noqa: BLE001 - a broken notifier must not break the sync bookkeeping
                _LOGGER.warning("Could not send the push through %s: %s", target, err)

    # ---- marks from the slideshow page --------------------------------------------------------------------
    @staticmethod
    def _update_manifest(out: Path, item_id: str, mark: str) -> None:
        """Reflect a mark in the published manifests (replaced atomically): fix / hide remove the item so the page stops
        showing it; like sets "liked" on it so the page keeps the heart lit in every cycle."""
        path = out / "manifest.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if mark == MARK_LIKE:
            items = data.get("items", [])
            hit = [e for e in items if e.get("id") == item_id and not e.get("liked")]
            if not hit:
                return
            for e in hit:
                e["liked"] = True
        else:
            items = [e for e in data.get("items", []) if e.get("id") != item_id]
            if len(items) == len(data.get("items", [])):
                return
        data["items"], data["count"] = items, len(items)
        for name, text in (("manifest.json", json.dumps(data, ensure_ascii=False, indent=1)),
                           ("manifest.txt", "\n".join(e["file"] for e in items) + "\n")):
            tmp = out / f".{name}.tmp"
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, out / name)

    async def async_mark(self, mark: str, item_id: str) -> dict:
        """Record a like / fix / never-show mark for a library item."""
        if mark not in MARKS:
            raise HomeAssistantError(f"Unknown mark {mark!r}")
        item = self.library.get(item_id)
        if item is None:
            raise HomeAssistantError("This item is not in the library (any more)")
        new = self.state.mark(mark, item, _utcnow())
        await self.hass.async_add_executor_job(self._update_manifest, Path(self.entry.data[CONF_OUTPUT_DIR]), item_id, mark)
        self._save()
        self.async_set_updated_data(self.snapshot())
        return {"mark": mark, "new": new, "path": item.path}

    # ---- the daily report ----------------------------------------------------------------------------------
    async def _daily_report(self, now: datetime) -> None:
        try:
            await self.async_send_report()
        except HomeAssistantError as err:
            _LOGGER.warning("Daily report not sent: %s", err)

    def _mail_service(self) -> str:
        names = [n for n in self.hass.services.async_services_for_domain("notify") if "gmail" in n]
        if not names:
            raise HomeAssistantError("No Gmail notify service found (set up the Google Mail integration)")
        return sorted(names)[0]

    async def _deliver(self, target: str, rep) -> None:
        target = str(target).strip()
        if target.startswith("notify."):
            service, data = target.split(".", 1)[1], {"title": rep.subject, "message": rep.text}
        elif "@" in target:
            service, data = self._mail_service(), {"title": rep.subject, "message": rep.html, "target": [target]}   # sent as HTML
        else:
            raise HomeAssistantError(f"Cannot send to {target!r}: not an e-mail address or a notify service")
        await self.hass.services.async_call("notify", service, data, blocking=True)

    async def async_send_report(self) -> dict:
        """E-mail (or push) the marks collected since the last report, then clear them. Nothing marked = nothing sent."""
        cfg = self.cfg
        rep = build_report(self.state.pending, self.library, cfg, dt_util.now().replace(tzinfo=None))
        if rep is None:
            return {"sent": False, "reason": "nothing was marked"}
        targets = [t for t in cfg[OPT_REPORT_NOTIFY] if str(t).strip()]
        if not targets:
            return {"sent": False, "reason": "no recipients are set"}
        errors = []
        for target in targets:
            try:
                await self._deliver(target, rep)
            except Exception as err:  # noqa: BLE001 - report every failed recipient
                errors.append(f"{target}: {err}")
        if len(errors) == len(targets):                       # nobody got it: keep the marks for the next try
            self.hass.bus.async_fire(EVENT_SYNC_FAILED, {"stage": "report", "error": "; ".join(errors)})
            raise HomeAssistantError("Report not sent: " + "; ".join(errors))
        self.state.drain_pending()
        self._save()
        self.async_set_updated_data(self.snapshot())
        self.hass.bus.async_fire(EVENT_REPORT_SENT, {"subject": rep.subject, "counts": rep.counts, "errors": errors})
        return {"sent": True, "subject": rep.subject, "counts": rep.counts, "errors": errors}

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
            "last_sync": self.state.last_sync or {}, "last_sync_ok": (self.state.last_sync or {}).get("ok"),
            "last_sync_at": (self.state.last_sync or {}).get("at"), "last_sync_error": (self.state.last_sync or {}).get("error"),
            "today": len(self.state.today), "fails_in_row": self.state.fails_in_row,
            "likes": self.state.totals.get("like", 0), "likes_pending": len(self.state.pending["like"]),
            "fixes": self.state.totals.get("fix", 0), "fixes_pending": len(self.state.pending["fix"]),
            "hidden_pending": len(self.state.pending["hide"]),
            "shown_photo": len(self.state.used[KIND_PHOTO]), "shown_video": len(self.state.used[KIND_VIDEO]),
            "progress_photo": self.state.progress(KIND_PHOTO, photos),
            "progress_video": self.state.progress(KIND_VIDEO, videos),
            "cycle_photo": self.state.cycles[KIND_PHOTO], "cycle_video": self.state.cycles[KIND_VIDEO],
        }
