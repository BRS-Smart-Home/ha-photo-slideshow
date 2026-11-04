"""The daily 08:00 report (likes, fix / delete, never show again). Pure Python, no Home Assistant imports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Mapping, Sequence

from .const import MARK_FIX, MARK_HIDE, MARK_LIKE, OPT_EXCLUDE_FILES
from .library import Item
from .rules import suggest_hidden_name
from .title import title_from_path

DRIVE_FILE_URL = "https://drive.google.com/file/d/{id}/view"


@dataclass
class Report:
    subject: str
    text: str
    html: str
    counts: dict


def _entry(e: Mapping, items: Mapping[str, Item]) -> dict:
    item = items.get(e["id"])
    path = item.path if item else e.get("path", "?")
    parts = path.split("/")
    t = title_from_path(parts)
    return {
        "id": e["id"], "path": path, "name": parts[-1],
        "title": " - ".join(t.lines), "url": DRIVE_FILE_URL.format(id=e["id"]),
    }


def build_report(pending: Mapping[str, Sequence[Mapping]], items: Mapping[str, Item], cfg: Mapping, now: datetime) -> Report | None:
    """Return None when nothing was marked (no marks, no report)."""
    counts = {m: len(pending.get(m, [])) for m in (MARK_LIKE, MARK_FIX, MARK_HIDE)}
    if not any(counts.values()):
        return None
    sections = [
        (MARK_LIKE, "Liked - share with family", "Open the link in Google Drive, then press Share."),
        (MARK_FIX, "Fix / delete", "Open the link to fix the photo or delete it if you have it elsewhere."),
        (MARK_HIDE, "Never show again", None),
    ]
    text_lines = [f"Travel Slideshow - {now.strftime('%d %b %Y')}", ""]
    html = [f"<h2>Travel Slideshow - {escape(now.strftime('%d %b %Y'))}</h2>"]
    for mark, heading, hint in sections:
        entries = [_entry(e, items) for e in pending.get(mark, [])]
        if not entries:
            continue
        text_lines.append(f"{heading} ({len(entries)})")
        html.append(f"<h3>{escape(heading)} ({len(entries)})</h3>")
        if hint:
            text_lines.append(hint)
            html.append(f"<p>{escape(hint)}</p>")
        html.append("<ul>")
        for e in entries:
            text_lines.append(f"- {e['title']}  [{e['path']}]")
            text_lines.append(f"  {e['url']}")
            line = f"<li><b>{escape(e['title'])}</b><br><small>{escape(e['path'])}</small><br><a href=\"{e['url']}\">{e['url']}</a>"
            if mark == MARK_HIDE:
                new_name = suggest_hidden_name(e["name"], cfg[OPT_EXCLUDE_FILES])
                text_lines.append(f"  To hide it for good rename it to: {new_name} (or delete it)")
                line += f"<br>Rename to <code>{escape(new_name)}</code> to hide it for good, or delete it."
            html.append(line + "</li>")
        html.append("</ul>")
        text_lines.append("")
    parts = []
    if counts[MARK_LIKE]:
        parts.append(f"{counts[MARK_LIKE]} liked")
    if counts[MARK_FIX]:
        parts.append(f"{counts[MARK_FIX]} to fix")
    if counts[MARK_HIDE]:
        parts.append(f"{counts[MARK_HIDE]} hidden")
    subject = "Travel Slideshow: " + ", ".join(parts)
    return Report(subject, "\n".join(text_lines).rstrip() + "\n", "\n".join(html), counts)
