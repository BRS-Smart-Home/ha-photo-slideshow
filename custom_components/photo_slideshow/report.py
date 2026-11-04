"""The daily 08:00 report (likes, fix / delete, never show again). Pure Python, no Home Assistant imports.

`html` is the e-mail body (Gmail ignores line breaks in plain text, so mails are sent as HTML); `text` is the plain version
used for push notifications.
"""
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

# colour of the card edge and heading per mark
COLORS = {MARK_LIKE: "#d6336c", MARK_FIX: "#e8890c", MARK_HIDE: "#6c757d"}


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
        "id": e["id"], "path": path, "name": parts[-1], "lines": list(t.lines),
        "title": " - ".join(t.lines), "url": DRIVE_FILE_URL.format(id=e["id"]),
    }


def _card(mark: str, e: Mapping, new_name: str | None) -> str:
    color = COLORS[mark]
    lines = "<br>".join(escape(x) for x in e["lines"]) or escape(e["name"])
    extra = ""
    if new_name:
        extra = (f'<div style="margin-top:6px;font-size:13px;color:#444">To hide it for good, rename it in Drive to '
                 f'<code style="background:#e9ecef;padding:1px 4px">{escape(new_name)}</code> (or delete it).</div>')
    return (
        f'<div style="margin:10px 0;padding:10px 14px;border-left:5px solid {color};background:#f5f5f5;border-radius:3px">'
        f'<div style="font-size:15px;line-height:1.4"><b>{lines}</b></div>'
        f'<div style="margin-top:4px;font-size:12px;color:#777">{escape(e["path"])}</div>'
        f'<div style="margin-top:8px"><a href="{e["url"]}" style="display:inline-block;padding:6px 14px;background:{color};'
        f'color:#ffffff;text-decoration:none;border-radius:4px;font-size:13px">Open in Google Drive</a></div>'
        f"{extra}</div>"
    )


def build_report(pending: Mapping[str, Sequence[Mapping]], items: Mapping[str, Item], cfg: Mapping, now: datetime) -> Report | None:
    """Return None when nothing was marked (no marks, no report)."""
    counts = {m: len(pending.get(m, [])) for m in (MARK_LIKE, MARK_FIX, MARK_HIDE)}
    if not any(counts.values()):
        return None
    sections = [
        (MARK_LIKE, "Liked", "Share these with the family: open the link in Google Drive, then press Share."),
        (MARK_FIX, "Fix or delete", "Open the link to fix the photo, or delete it if you have it elsewhere."),
        (MARK_HIDE, "Never show again", None),
    ]
    date = now.strftime("%d %b %Y")
    text_lines = [f"Travel Slideshow - {date}", ""]
    html = [
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;color:#222">',
        f'<h2 style="margin:0 0 4px">Travel Slideshow</h2><div style="color:#777;font-size:13px">{escape(date)}</div>',
    ]
    for mark, heading, hint in sections:
        entries = [_entry(e, items) for e in pending.get(mark, [])]
        if not entries:
            continue
        text_lines.append(f"{heading.upper()} ({len(entries)})")
        html.append(f'<h3 style="margin:26px 0 2px;color:{COLORS[mark]}">{escape(heading)} ({len(entries)})</h3>')
        if hint:
            text_lines.append(hint)
            html.append(f'<div style="font-size:13px;color:#555">{escape(hint)}</div>')
        for e in entries:
            new_name = suggest_hidden_name(e["name"], cfg[OPT_EXCLUDE_FILES]) if mark == MARK_HIDE else None
            text_lines.append("")
            text_lines.extend(e["lines"] or [e["name"]])
            text_lines.append(e["path"])
            text_lines.append(e["url"])
            if new_name:
                text_lines.append(f"To hide it for good rename it to: {new_name} (or delete it)")
            html.append(_card(mark, e, new_name))
        text_lines.append("")
    html.append("</div>")
    parts = []
    if counts[MARK_LIKE]:
        parts.append(f"{counts[MARK_LIKE]} liked")
    if counts[MARK_FIX]:
        parts.append(f"{counts[MARK_FIX]} to fix")
    if counts[MARK_HIDE]:
        parts.append(f"{counts[MARK_HIDE]} hidden")
    subject = "Travel Slideshow: " + ", ".join(parts)
    return Report(subject, "\n".join(text_lines).rstrip() + "\n", "".join(html), counts)
