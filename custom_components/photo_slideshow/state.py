"""Persistent state: what was shown in this cycle, hidden items, marks waiting for the report. Pure Python."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping

from .const import KIND_PHOTO, KIND_VIDEO, MARK_FIX, MARK_HIDE, MARK_LIKE, MARKS
from .library import Item


@dataclass
class State:
    used: dict[str, set[str]] = field(default_factory=lambda: {KIND_PHOTO: set(), KIND_VIDEO: set()})
    cycles: dict[str, int] = field(default_factory=lambda: {KIND_PHOTO: 1, KIND_VIDEO: 1})
    hidden: dict[str, dict] = field(default_factory=dict)             # id -> {"path", "at"}
    pending: dict[str, list[dict]] = field(default_factory=lambda: {m: [] for m in MARKS})
    totals: dict[str, int] = field(default_factory=lambda: {"shown": 0, MARK_LIKE: 0, MARK_FIX: 0, MARK_HIDE: 0})
    today: list[str] = field(default_factory=list)                   # ids in today's slideshow
    last_sync: dict = field(default_factory=dict)
    last_scan: dict = field(default_factory=dict)
    fails_in_row: int = 0

    # ---- (de)serialisation for the Home Assistant Store --------------------------------
    def to_dict(self) -> dict:
        return {
            "used": {k: sorted(v) for k, v in self.used.items()},
            "cycles": self.cycles, "hidden": self.hidden, "pending": self.pending, "totals": self.totals,
            "today": self.today, "last_sync": self.last_sync, "last_scan": self.last_scan,
            "fails_in_row": self.fails_in_row,
        }

    @classmethod
    def from_dict(cls, d: Mapping | None) -> "State":
        s = cls()
        if not d:
            return s
        for k in (KIND_PHOTO, KIND_VIDEO):
            s.used[k] = set(d.get("used", {}).get(k, []))
            s.cycles[k] = int(d.get("cycles", {}).get(k, 1))
        s.hidden = dict(d.get("hidden", {}))
        for m in MARKS:
            s.pending[m] = list(d.get("pending", {}).get(m, []))
        s.totals.update(d.get("totals", {}))
        s.today = list(d.get("today", []))
        s.last_sync = dict(d.get("last_sync", {}))
        s.last_scan = dict(d.get("last_scan", {}))
        s.fails_in_row = int(d.get("fails_in_row", 0))
        return s

    # ---- cycle bookkeeping ---------------------------------------------------------------
    def hidden_ids(self) -> set[str]:
        return set(self.hidden)

    def mark_used(self, kind: str, ids: Iterable[str], cycle_reset: bool = False) -> None:
        if cycle_reset:
            self.used[kind].clear()
            self.cycles[kind] += 1
        self.used[kind].update(ids)

    def progress(self, kind: str, library_count: int) -> float:
        """Share of the library already shown in this cycle, 0-100."""
        return round(100.0 * len(self.used[kind]) / library_count, 1) if library_count else 0.0

    # ---- marks from the slideshow ----------------------------------------------------------
    def mark(self, mark: str, item: Item, now: datetime) -> bool:
        """Record a like / fix / hide. Returns False when the item is already marked the same way."""
        if mark not in MARKS:
            raise ValueError(f"unknown mark {mark!r}")
        if any(e["id"] == item.id for e in self.pending[mark]):
            return False
        self.pending[mark].append({"id": item.id, "path": item.path, "at": now.isoformat()})
        self.totals[mark] = self.totals.get(mark, 0) + 1
        if mark in (MARK_FIX, MARK_HIDE) and item.id in self.today:
            self.today.remove(item.id)                              # leaves today's slideshow at once
        if mark == MARK_HIDE:
            self.hidden[item.id] = {"path": item.path, "at": now.isoformat()}
        return True

    def drain_pending(self) -> dict[str, list[dict]]:
        """Hand the marks to the daily report and clear them (hidden items stay hidden)."""
        out = {m: list(v) for m, v in self.pending.items()}
        self.pending = {m: [] for m in MARKS}
        return out

    def pending_counts(self) -> dict[str, int]:
        return {m: len(v) for m, v in self.pending.items()}

    def unhide(self, item_id: str) -> bool:
        return self.hidden.pop(item_id, None) is not None

    def prune_hidden(self, library_ids: set[str]) -> list[str]:
        """After a COMPLETE scan: forget hidden items whose file is gone or now matches an exclusion rule."""
        gone = [i for i in self.hidden if i not in library_ids]
        for i in gone:
            del self.hidden[i]
        return gone
