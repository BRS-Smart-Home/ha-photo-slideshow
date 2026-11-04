"""Library rules: which Drive files belong to the slideshow. Pure Python, no Home Assistant imports."""
from __future__ import annotations

import fnmatch
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .const import (
    KIND_PHOTO,
    KIND_VIDEO,
    OPT_EXCLUDE_FILES,
    OPT_EXCLUDE_FOLDERS,
    OPT_MAX_VIDEO_MB,
    OPT_MAX_VIDEO_SECONDS,
    OPT_PHOTO_FORMATS,
    OPT_VIDEO_FORMATS,
)

_WILDCARDS = "*?["


def is_glob(pattern: str) -> bool:
    return any(c in pattern for c in _WILDCARDS)


def match_glob(pattern: str, text: str) -> bool:
    """Case-insensitive glob match (`*`, `?`, `[a-z]`)."""
    return fnmatch.fnmatchcase(text.lower(), pattern.strip().lower())


def match_segment(pattern: str, segment: str) -> bool:
    """Folder-name rule.

    A pattern with wildcards is a glob over the whole folder name. A plain pattern matches when the folder name equals it
    or contains it as a whole word/phrase (so "temp" matches "aaaa temp" and "temp_old" but not "Temple").
    """
    p = pattern.strip()
    if not p:
        return False
    if is_glob(p):
        return match_glob(p, segment)
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(p.lower()) + r"(?![A-Za-z0-9])", segment.lower()) is not None


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[1].lower() if "." in name else ""


@dataclass(frozen=True)
class Decision:
    included: bool
    kind: str | None
    reason: str          # "ok" or why it is out: format, root-file, excluded-folder, excluded-name, video-*


def evaluate(
    parts: Sequence[str],
    cfg: Mapping,
    size: int | None = None,
    duration_ms: int | None = None,
) -> Decision:
    """Decide whether a file belongs to the library.

    `parts` is the path below the photo root, e.g. ["2022 Spain", "Montserrat", "IMG_1.heic"].
    """
    if not parts:
        return Decision(False, None, "empty")
    *folders, name = parts
    ext = ext_of(name)
    if ext in cfg[OPT_PHOTO_FORMATS]:
        kind = KIND_PHOTO
    elif ext in cfg[OPT_VIDEO_FORMATS]:
        kind = KIND_VIDEO
    else:
        return Decision(False, None, "format")
    if not folders:
        return Decision(False, kind, "root-file")           # files directly in the root are never shown
    for seg in folders:
        if any(match_segment(p, seg) for p in cfg[OPT_EXCLUDE_FOLDERS]):
            return Decision(False, kind, "excluded-folder")
    if any(match_glob(p, name) for p in cfg[OPT_EXCLUDE_FILES]):
        return Decision(False, kind, "excluded-name")
    if kind == KIND_VIDEO:
        if duration_ms is None:
            return Decision(False, kind, "video-unknown-length")
        if duration_ms > float(cfg[OPT_MAX_VIDEO_SECONDS]) * 1000:
            return Decision(False, kind, "video-too-long")
        if size is not None and size > float(cfg[OPT_MAX_VIDEO_MB]) * 1024 * 1024:
            return Decision(False, kind, "video-too-big")
    return Decision(True, kind, "ok")


def dry_run(entries: Iterable[tuple[Sequence[str], int | None, int | None]], cfg: Mapping) -> Counter:
    """Count how many files each rule keeps or removes. `entries` = (parts, size, duration_ms)."""
    out: Counter = Counter()
    for parts, size, duration in entries:
        d = evaluate(parts, cfg, size, duration)
        out[(d.kind or "other") + ":" + d.reason] += 1
    return out


def hidden_suffix(patterns: Sequence[str]) -> str:
    """The rename suffix implied by the first `*<suffix>.*` file pattern (default "_hide")."""
    for p in patterns:
        m = re.fullmatch(r"\*([^*?\[\]]+)\.\*", p.strip())
        if m:
            return m.group(1)
    return "_hide"


def suggest_hidden_name(name: str, patterns: Sequence[str]) -> str:
    """`IMG_1.jpg` -> `IMG_1_hide.jpg`: the new name that makes a file match the exclusion pattern."""
    suffix = hidden_suffix(patterns)
    if "." in name:
        base, ext = name.rsplit(".", 1)
        return f"{base}{suffix}.{ext}"
    return name + suffix
