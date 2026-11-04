"""Building one day's slideshow: pick, fetch, replace failures. Pure Python, no Home Assistant imports.

The actual download / conversion is injected as `fetch`, so this logic can be tested with fakes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, Mapping

from .const import KIND_PHOTO, KIND_VIDEO
from .library import Item, pick

# fetch(item, counter) -> local file name; raises on any problem (download, conversion, too big ...)
Fetch = Callable[[Item, int], Awaitable[str]]

MAX_ATTEMPT_FACTOR = 3          # per kind we try at most 3x the wanted number of items before giving up


@dataclass
class DayResult:
    done: list[tuple[Item, str]] = field(default_factory=list)       # photos first, then videos, in show order
    failed: list[dict] = field(default_factory=list)                  # {"id", "path", "error"}
    cycle_reset: dict[str, bool] = field(default_factory=lambda: {KIND_PHOTO: False, KIND_VIDEO: False})
    short: dict[str, int] = field(default_factory=lambda: {KIND_PHOTO: 0, KIND_VIDEO: 0})
    ids: dict[str, list[str]] = field(default_factory=lambda: {KIND_PHOTO: [], KIND_VIDEO: []})


async def build_day(
    library: Mapping[str, Item],
    used: Mapping[str, set[str]],
    hidden: set[str],
    targets: Mapping[str, int],
    fetch: Fetch,
    rng: random.Random | None = None,
) -> DayResult:
    """Fetch `targets[kind]` items per kind; an item that fails is replaced by another random unused one.

    Nothing is recorded as used here: the caller does that only after the whole day was published.
    """
    rng = rng or random.Random()
    res = DayResult()
    for kind in (KIND_PHOTO, KIND_VIDEO):
        want = int(targets.get(kind, 0))
        attempted: set[str] = set()
        tries = 0
        while len(res.ids[kind]) < want and tries < want * MAX_ATTEMPT_FACTOR:
            need = want - len(res.ids[kind])
            pr = pick(library, kind, need, set(used[kind]), hidden, rng, exclude=attempted)
            if not pr.items:
                break
            if pr.cycle_reset:
                res.cycle_reset[kind] = True
            for item in pr.items:
                attempted.add(item.id)
                tries += 1
                try:
                    fname = await fetch(item, len(res.done) + 1)
                except Exception as err:  # noqa: BLE001 - any failure of one item is only that item's problem
                    res.failed.append({"id": item.id, "path": item.path, "error": f"{type(err).__name__}: {err}"[:200]})
                    continue
                res.done.append((item, fname))
                res.ids[kind].append(item.id)
        res.short[kind] = want - len(res.ids[kind])
    # keep photos first, then videos, whatever the order of completion
    res.done.sort(key=lambda e: 0 if e[0].kind == KIND_PHOTO else 1)
    return res


def day_is_acceptable(res: DayResult, targets: Mapping[str, int]) -> tuple[bool, str]:
    """A day is published when at least half of the wanted photos were fetched (videos are optional)."""
    want = int(targets.get(KIND_PHOTO, 0))
    got = len(res.ids[KIND_PHOTO])
    if want and got * 2 < want:
        return False, f"only {got} of {want} photos could be fetched"
    return True, ""


def photo_target_ext(ext: str) -> str:
    """File extension of the local copy: JPG/PNG stay, everything else becomes JPG."""
    ext = ext.lower()
    return ext if ext in ("jpg", "jpeg", "png") else "jpg"


def used_ids_to_record(res: DayResult) -> Iterable[tuple[str, list[str], bool]]:
    for kind in (KIND_PHOTO, KIND_VIDEO):
        yield kind, res.ids[kind], res.cycle_reset[kind]
