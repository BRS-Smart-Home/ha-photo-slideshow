# ha-photo-slideshow

Private Home Assistant custom integration **`photo_slideshow`** ("Travel Slideshow"): keeps the travel-photo
slideshow on the Dash3 dashboard fed, reacts to problems, and keeps statistics.

> **Status: design / spec** (agreed 2026-11-04). Replaces `scripts/sync_photos.sh` + the `shell_command`
> `sync_gdrive_photos` + `rclone` / `magick` binaries in `/config/scripts`.

## Why

The old script has `scope = drive` (full read/write access to the whole Google Drive), no error handling and a broken
HEIC step: `mogrify: command not found`, so every HEIC photo (25 % of the library) was deleted and marked "used", the
folder held 72 photos instead of 100, nothing was resized, and the photo list (`dir.txt`) was built by hand on a PC.

## Source and security

- **Google Drive API, read-only, through a service account** (a robot identity, not a Gmail account). The photo root folder
  (`Pictures`) is shared with the service account as **Viewer**; it can see nothing else, can change nothing and does not
  expire. The project is owned by a spare Google account (`kitsune.brs2`), the photos by the main account.
- The service account JSON key is pasted into the config flow and stored in the config entry (`.storage`, never in git).
- The integration can never delete or rename originals. "Delete" always means "hide in the slideshow and tell me".

## Library rules (all adjustable in the integration options)

| Option | Default |
|---|---|
| Included folders | the `YYYY Country` folders, `01 me`, `02 Family` |
| Excluded folders (patterns, case-insensitive, whole words) | `00 Resources`, `03 Intros`, `temp`, `tmp`, `Motion Graphics Template Media` |
| **Excluded file-name patterns** (glob, case-insensitive) | `*_hide.*` (rename a photo to `IMG_1234_hide.jpg` and it leaves the library for good) |
| Photo formats | JPG, JPEG, PNG, HEIC, TIFF, BMP, GIF (HEIC/TIFF/BMP/GIF converted to JPG) |
| Video formats | MP4, MOV |
| Skipped | RAW (DNG, RW2), PSD, everything else |

A *dry run* service reports how many files match each rule before anything is changed.

## Nightly sync (00:00, adjustable)

- **50 items per day = 47 photos + 3 videos** (both adjustable). Each item is shown once per cycle:
  photos 18,232 / 47 = about 388 days, videos about 1,250 / 3 = about 417 days.
- Photos: resized to **1024 px max** (adjustable), converted to JPG where needed (Pillow + pillow-heif).
- **Videos: up to 30 s and 60 MB** (both adjustable), judged from Google's metadata before downloading; converted to a small
  muted 720p MP4 with ffmpeg; played once.
- A failed download or conversion is replaced by another item; an item is marked "used" only when it worked.
- The manifest is written atomically and carries title, place, date and type for each file.

## Weekly scan (Sunday night, adjustable)

Rescans the Drive folders, adds new files to the library (new items get a boost for 7 days, adjustable), drops files that were
deleted, renamed to match an exclusion pattern or moved out of an included folder, and updates the statistics.

## Titles and metadata

- Base title from the folder path (`2022 Spain / Montserrat` -> "Year: 2022, Location: Spain, Montserrat"), so photos
  without any metadata work.
- Enriched from Google's file metadata (no download needed): exact date, camera, GPS -> nearest town from a small bundled
  offline list. No external lookups.

## Buttons on the slideshow (three marks)

| Button | Immediately | Next day 08:00 report | Afterwards |
|---|---|---|---|
| ♥ **Like** | nothing changes (just for fun) | listed with a **Google Drive link** (to share with family) | mark cleared |
| 🔧 **Fix / delete** (one icon) | the item leaves today's slideshow | listed with its Drive link and full path | mark cleared (it is not shown again this cycle anyway) |
| ✖ **Never show again** | the item leaves today's slideshow | listed with the path and the rename hint (`..._hide.jpg`) or delete it | stays hidden in the integration until the file is renamed/deleted (then pruned); un-hide in the options |

The report is sent **every day at 08:00** (adjustable) by e-mail (and optionally push); no marks, no report.

## Sensors, services, events

- Sensors: items shown so far in this cycle and cycle progress %, library size (photos/videos), items remaining, new items
  in the last scan, likes and fix requests (pending and total), hidden items, last sync (time, status, counts), photo
  folder size, last error.
- `binary_sensor` **Sync problem**: last sync failed, many items failed, or no successful sync for 36 h.
- Buttons/services: sync now, rescan now, dry run, send report now, un-hide, mark (`like`, `fix`, `hide`).
- Events: `photo_slideshow_sync_failed`, `photo_slideshow_report_sent`. Repairs entries with a plain explanation (login/
  share problem, HEIC support missing, disk almost full, ...) and a push after two failed syncs in a row.
- Diagnostics download, long-term statistics for the counters.

## Dashboard

The slideshow stays **exactly where it is**: the iframe of `index.html` in Dash3. `index.html` keeps the mode videos; the
photo part reads the new manifest and gets the three buttons (it already holds the HA token for service calls).

## Build phases

1. Core: config flow + options, Drive scan, selection and sync into a test folder, statistics, errors, repairs.
2. Marks, the 08:00 report, buttons on the page.
3. Cut over (after a few clean nights): point the page at the new folder, remove the old script, `shell_command` and
   binaries, revoke the old full-access Drive token.
4. Smart camera moves: a focus point per photo (lightweight saliency, computed at sync time) so the page pans and zooms
   toward the subject.

## Wish list

Face-aware camera moves, RAW support, longer videos (stills), PSD, a native custom card replacing the iframe.
Google Photos was considered and rejected: since 31 March 2025 its API only reads content an app uploaded itself.

## Names

Repository `BRS-Smart-Home/ha-photo-slideshow` (private), domain `photo_slideshow`, Google Cloud project `ha-photo-slideshow`.
