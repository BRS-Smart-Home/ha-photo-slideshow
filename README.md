<p align="center">
  <img src="custom_components/photo_slideshow/brand/icon@2x.png" alt="Travel Slideshow" width="140">
</p>

<h1 align="center">Travel Slideshow</h1>

<p align="center">
  A Home Assistant integration that keeps a travel photo and video slideshow fed from Google Drive.<br>
  Read-only access, error handling, statistics and a daily report.
</p>

> **Private repository.** Installed through HACS as a custom repository (category *Integration*); a manual copy into the
> Home Assistant `custom_components` folder also works. The full design is in [docs/SPEC.md](docs/SPEC.md).

## Status

| Version | What it does |
|---|---|
| 0.1.x | Connects to Google Drive with a **service account** (read-only), scans the photo folder, applies the folder / file / format rules and reports the numbers as sensors. |
| 0.2 | Nightly sync into `www/slideshow`: 47 photos + 3 videos, equal chance for every unused item, photos at original size (HEIC/TIFF/BMP/GIF become JPG), videos cut at 30 s and converted to a small MP4, `manifest.json`, failed items replaced, repair + event on errors, push after 2 failed syncs. |
| 0.3 | Marks (like / fix / never show) with services and a daily e-mail report with Drive links; the old `sync_photos.sh` script was removed (cut-over done). |
| 0.4 | Options: seconds per photo, show / hide every element of the slideshow page (navigation keys off by default); manifest carries capture time, path and the options; marks also work for items no longer in the library; "Send report now" (does not clear the list, only the scheduled report does). |
| 0.5.0 | Sensors: unique photos / videos shown (ever) and photos / videos still to show in this cycle. |
| 0.6.0 | New option "Show: item counter": a small `12 / 50` in the top right corner of the slideshow page (off by default). |
| 0.6.1 | Release version bump for the HACS download (no code change since 0.6.0). |
| 0.7.0 | The slideshow page now ships with the integration at `/photo_slideshow/index.html` and updates with it. Optional extras (mode videos, exit countdown, cleaning note) are options, off by default. |
| **0.7.1** (this) | The page passes its `?number` on to its style sheet, so raising the number in the dashboard URL refreshes both after an update. |

## Show the slideshow

The integration serves the page itself, so there is nothing to copy. Add a **Webpage** card (or an iframe card) to a dashboard:

```yaml
type: iframe
url: /photo_slideshow/index.html
aspect_ratio: 56%
```

or open `http://<your-home-assistant>:8123/photo_slideshow/index.html` full screen (a kiosk tablet, for example). The page is never
cached for long, but some kiosk browsers keep a copy anyway: put a number behind the address (`/photo_slideshow/index.html?1`) and raise it after every update of the integration, which then also refreshes the style sheet.

The page shows today's items (written to `/config/www/slideshow` by the nightly sync) with gestures: **tap** = pause / play,
**swipe** = next / previous. The like / fix / never-show buttons need to talk to Home Assistant: inside a dashboard card the page
uses your logged-in session; on a screen without one (a kiosk), create a long-lived access token and save it as
`/config/www/ha-token.js` containing `const ha_token = "<token>";`. Keep that file private. Your own colours or fonts can go into
`/config/www/slideshow_custom.css`, which the page loads when it exists. `?media=/local/other/` points the page to another output
folder.

### Optional extras (off by default)

Options of the integration, all empty by default and then never touched:

| Option | What it does |
|---|---|
| Mode video entity | An `input_text` such as `input_text.video_mode`. `home` runs the slideshow; any other value (`coffee`, `exit`, `sleep` ...) plays `<folder>/<value>.mp4` in a loop instead. |
| Mode video folder | Where those videos live, default `/local/webmedia/` (`/config/www/webmedia`). |
| Exit countdown entity and minutes | An `input_boolean`: while it is on and the mode is `exit`, a flip clock counts the minutes until the house is armed. |
| Vacuum entities | While the mode is `exit` and any of these is cleaning, a "Cleaning: in progress" note shows. |

## Install

1. **HACS:** add `https://github.com/BRS-Smart-Home/ha-photo-slideshow` as a custom repository (category *Integration*), install
   *Travel Slideshow* and restart Home Assistant. HACS needs access to the GitHub account that owns this private repository.
   **Manual:** copy the folder `custom_components/photo_slideshow` into `/config/custom_components/` and restart Home Assistant.
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
