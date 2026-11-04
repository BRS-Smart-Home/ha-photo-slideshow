"""File names and the manifest written for the slideshow page. Pure Python, no Home Assistant imports.

Local file names keep the convention of the old script so the current `index.html` keeps working during the cut-over:
`<n>_<path with / as _AAA_ and spaces as _>.<ext>`, e.g. `3_2022_Spain_AAA_Montserrat_AAA_IMG_1.jpg`.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from .library import Item
from .title import enrich, title_from_path


def local_name(counter: int, parts: Sequence[str], ext: str) -> str:
    stem = "/".join(parts).rsplit(".", 1)[0] if "." in parts[-1] else "/".join(parts)
    clean = stem.replace("/", "_AAA_").replace(" ", "_")
    return f"{counter}_{clean}.{ext}"


def build_manifest(files: Sequence[tuple[Item, str]], photo_seconds: int = 15) -> dict:
    """`files` = (item, local file name) for every item that was downloaded successfully today."""
    entries = []
    for item, fname in files:
        title = enrich(title_from_path(item.parts), item.meta)
        entries.append({
            "id": item.id, "file": fname, "kind": item.kind, "lines": title.lines,
            "year": title.year, "country": title.country, "place": title.place,
        })
    return {"version": 1, "photo_seconds": photo_seconds, "count": len(entries), "items": entries}


def build_legacy_manifest(files: Sequence[tuple[Item, str]]) -> str:
    """The old `manifest.txt`: one file name per line (the current page reads this)."""
    return "\n".join(fname for _, fname in files) + "\n"
