"""Titles for the slideshow. Pure Python, no Home Assistant imports.

The base title comes from the folder path (it must work for photos without any metadata); Drive's file metadata can
enrich it. The output matches the old `index.html` text: "Year: 2019 / Location: United States, Los Angeles".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

_YEAR_FOLDER = re.compile(r"^(\d{4})\s+(.*)$")
NO_PLACE = "Top Secret"          # kept from the old page: shown when a photo has no sub-folder


@dataclass
class Title:
    year: str | None
    country: str
    place: str
    lines: list[str] = field(default_factory=list)

    def html(self) -> str:
        return "<br>".join(self.lines)


def title_from_path(parts: Sequence[str]) -> Title:
    """["2022 Spain", "Montserrat", "IMG.heic"] -> Year: 2022 / Location: Spain, Montserrat."""
    folders = list(parts[:-1])
    main = folders[0] if folders else ""
    sub = folders[1] if len(folders) > 1 else None
    m = _YEAR_FOLDER.match(main)
    year = m.group(1) if m else None
    country = m.group(2) if m else main
    place = sub or NO_PLACE
    lines = []
    if year:
        lines.append(f"Year: {year}")
    lines.append(f"Location: {country}, {place}")
    return Title(year, country, place, lines)


def parse_exif_time(value: str | None) -> datetime | None:
    """Drive's imageMediaMetadata.time looks like '2022:08:14 17:31:06'."""
    if not value:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def taken_text(meta: Mapping | None) -> str | None:
    """The exact moment the picture was taken, 'YYYY-MM-DD HH:MM:SS' (camera local time), or None when unknown / implausible."""
    taken = parse_exif_time((meta or {}).get("time"))
    if taken and 1990 <= taken.year <= datetime.now().year + 1:
        return taken.strftime("%Y-%m-%d %H:%M:%S")
    return None


def enrich(title: Title, meta: Mapping | None) -> Title:
    """Add the exact date from the file's metadata, when there is one (sensible years only)."""
    if not meta:
        return title
    taken = parse_exif_time(meta.get("time"))
    if taken and 1990 <= taken.year <= datetime.now().year + 1:
        title.lines.append("Date: " + taken.strftime("%d %b %Y").lstrip("0"))
    return title
