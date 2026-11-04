"""The photo/video library and the daily pick. Pure Python, no Home Assistant imports."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping, Sequence


@dataclass
class Item:
    id: str                                   # Drive file id
    parts: tuple[str, ...]                    # path below the root, last = file name
    kind: str                                 # "photo" | "video"
    added: datetime                           # when the weekly scan first saw it
    size: int | None = None
    modified: str | None = None
    duration_ms: int | None = None
    meta: dict | None = None                  # Drive imageMediaMetadata (time, location, camera ...)

    @property
    def name(self) -> str:
        return self.parts[-1]

    @property
    def path(self) -> str:
        return "/".join(self.parts)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "p": list(self.parts), "k": self.kind, "a": self.added.isoformat(),
            "s": self.size, "m": self.modified, "d": self.duration_ms, "x": self.meta,
        }

    @classmethod
    def from_dict(cls, d: Mapping) -> "Item":
        return cls(
            id=d["id"], parts=tuple(d["p"]), kind=d["k"], added=datetime.fromisoformat(d["a"]),
            size=d.get("s"), modified=d.get("m"), duration_ms=d.get("d"), meta=d.get("x"),
        )


def merge_scan(old: Mapping[str, Item], found: Iterable[Item], now: datetime) -> tuple[dict[str, Item], dict]:
    """Result of a weekly scan: new items keep `added=now`, known items keep their first-seen time.

    Returns (library, summary) where summary has counts of new / removed / kept items.
    """
    library: dict[str, Item] = {}
    new = 0
    for it in found:
        prev = old.get(it.id)
        if prev:
            it.added = prev.added
        else:
            it.added = now
            new += 1
        library[it.id] = it
    removed = len([i for i in old if i not in library])
    return library, {"new": new, "removed": removed, "total": len(library)}


@dataclass
class PickResult:
    items: list[Item]
    cycle_reset: bool = False                 # the unused pool ran out: a new cycle starts
    short: int = 0                            # how many of the requested items could not be found


def pick(
    library: Mapping[str, Item],
    kind: str,
    k: int,
    used: set[str],
    hidden: set[str],
    rng: random.Random | None = None,
    exclude: Iterable[str] = (),
) -> PickResult:
    """Pick `k` items of `kind` uniformly at random: not shown in this cycle, not hidden, not in `exclude`.

    Every eligible item has the same chance (new files get no preference). When fewer than `k` unused items are left, they are
    all taken and the rest comes from the start of a new cycle (`cycle_reset=True`): the caller then clears its used set before
    recording the picks.
    """
    rng = rng or random.Random()
    skip = set(exclude)
    pool = [i for i in library.values() if i.kind == kind and i.id not in hidden and i.id not in skip]
    if k <= 0:
        return PickResult([])
    avail = [i for i in pool if i.id not in used]
    if len(avail) >= k:
        return PickResult(rng.sample(avail, k))
    picked = list(avail)                                     # take what is left, then start a new cycle
    taken = {p.id for p in picked}
    fresh = [i for i in pool if i.id not in taken]
    picked += rng.sample(fresh, min(k - len(picked), len(fresh)))
    return PickResult(picked, cycle_reset=True, short=k - len(picked))
