<p align="center">
  <img src="custom_components/photo_slideshow/brand/icon@2x.png" alt="Travel Slideshow" width="140">
</p>

<h1 align="center">Travel Slideshow</h1>

<p align="center">
  A Home Assistant integration that keeps a travel photo and video slideshow fed from Google Drive.<br>
  Read-only access, error handling, statistics and a daily report.
</p>

> **Private repository.** Installed by copying `custom_components/photo_slideshow` into the Home Assistant `custom_components`
> folder (HACS cannot install private repositories). The full design is in [docs/SPEC.md](docs/SPEC.md).

## Status

| Version | What it does |
|---|---|
| 0.1.x | Connects to Google Drive with a **service account** (read-only), scans the photo folder, applies the folder / file / format rules and reports the numbers as sensors. |
| 0.2 | Nightly sync into `www/slideshow`: 47 photos + 3 videos, equal chance for every unused item, photos at original size (HEIC/TIFF/BMP/GIF become JPG), videos cut at 30 s and converted to a small MP4, `manifest.json`, failed items replaced, repair + event on errors, push after 2 failed syncs. |
| 0.3 | Marks (like / fix / never show) with services and a daily e-mail report with Drive links; the old `sync_photos.sh` script was removed (cut-over done). |
| 0.4 | Options: seconds per photo, show / hide every element of the slideshow page (navigation keys off by default); manifest carries capture time, path and the options; marks also work for items no longer in the library; "Send report now" (does not clear the list, only the scheduled report does). |
| **0.5.0** (this) | Sensors: unique photos / videos shown (ever) and photos / videos still to show in this cycle. |

The slideshow page itself (`index.html`, gestures, gold dash styling, rolling date) lives in the Home Assistant config repo (`ha-config`, `www/index.html`).

## Install

1. Copy the folder `custom_components/photo_slideshow` into `/config/custom_components/` and restart Home Assistant.
2. **Settings > Devices & Services > Add integration > Travel Slideshow.**
3. Paste the **whole content of the service account key file** (the `.json` file) and the **Drive folder ID** (or the folder's web
   address). The key stays in this Home Assistant; it is never sent anywhere except to Google to sign in.

### Google side (once)

1. In the Google Cloud Console enable the **Google Drive API** for a project, create a **service account** and download a
   **JSON key**.
2. In Google Drive, **share the photo folder with the service account's e-mail address as Viewer**. It then sees that folder and
   nothing else, and cannot change or delete anything.

## Options

All rules are options of the integration (**Configure**), one entry per line:

| Option | Default | Notes |
|---|---|---|
| Folders to exclude | `temp`, `tmp` | any level; plain words match whole words (`temp` does not match `Temple`); entries with `* ? [ ]` are glob patterns |
| File-name patterns to exclude | `*_hide.*` | rename `IMG_1.jpg` to `IMG_1_hide.jpg` in Drive and it leaves the slideshow for good |
| Photo formats | jpg, jpeg, png, heic, tif, tiff, bmp, gif | separated by commas; photos keep their original size |
| Video formats | mp4, mov | up to 30 s and 60 MB by default |
| Photos / videos per day | 47 / 3 | |
| Weekly scan, daily sync, daily report | Sunday 03:00, 00:00, 08:00 | |

## Entities (0.1)

Sensors: photos in library, videos in library, files seen in Drive, excluded by rules (attribute `by_rule` lists the reasons),
new in last scan, hidden items, last scan (time, seconds, status), photo and video cycle progress. A **Scan problem** binary
sensor and a **Scan library now** button.

Services: `photo_slideshow.scan` and `photo_slideshow.dry_run` (count what the rules keep or remove, with the current options or
with rules you pass in, without changing anything).

## Development

The logic that needs no Home Assistant (rules, titles, picking, state, report, file names) is plain Python with tests in
`tests/test_logic.py` (`pytest`, or call `run_all()`).
