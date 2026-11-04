"""Constants and default options for the Travel Slideshow integration."""
from __future__ import annotations

DOMAIN = "photo_slideshow"
NAME = "Travel Slideshow"

# ---- config entry data --------------------------------------------------------
CONF_SERVICE_ACCOUNT = "service_account"      # the service-account JSON (stored in the entry, never in git)
CONF_ROOT_FOLDER_ID = "root_folder_id"        # Drive folder id of the photo root ("Pictures")
CONF_OUTPUT_DIR = "output_dir"                # where the slideshow files are written

# ---- options (all adjustable in the integration options) -----------------------
OPT_PHOTOS_PER_DAY = "photos_per_day"
OPT_VIDEOS_PER_DAY = "videos_per_day"
OPT_MAX_VIDEO_SECONDS = "max_video_seconds"
OPT_MAX_VIDEO_MB = "max_video_mb"
OPT_EXCLUDE_FOLDERS = "exclude_folders"
OPT_EXCLUDE_FILES = "exclude_files"
OPT_PHOTO_FORMATS = "photo_formats"
OPT_VIDEO_FORMATS = "video_formats"
OPT_SYNC_TIME = "sync_time"
OPT_SCAN_WEEKDAY = "scan_weekday"
OPT_SCAN_TIME = "scan_time"
OPT_REPORT_TIME = "report_time"
OPT_REPORT_NOTIFY = "report_notify"           # list of notify service names, e.g. ["notify.kitsune_brs2_gmail_com"]
OPT_FAILS_BEFORE_PUSH = "fails_before_push"

DEFAULT_OPTIONS: dict = {
    OPT_PHOTOS_PER_DAY: 47,
    OPT_VIDEOS_PER_DAY: 3,
    OPT_MAX_VIDEO_SECONDS: 30,
    OPT_MAX_VIDEO_MB: 60,
    # Folder rules apply to folder names at any level: a glob if they contain * ? [ ], else a whole-word match.
    OPT_EXCLUDE_FOLDERS: ["temp", "tmp"],
    OPT_EXCLUDE_FILES: ["*_hide.*"],
    OPT_PHOTO_FORMATS: ["jpg", "jpeg", "png", "heic", "tif", "tiff", "bmp", "gif"],
    OPT_VIDEO_FORMATS: ["mp4", "mov"],
    OPT_SYNC_TIME: "00:00",
    OPT_SCAN_WEEKDAY: 6,                         # 0 = Monday ... 6 = Sunday
    OPT_SCAN_TIME: "03:00",
    OPT_REPORT_TIME: "08:00",
    OPT_REPORT_NOTIFY: [],
    OPT_FAILS_BEFORE_PUSH: 2,
}

# ---- marks made from the slideshow ------------------------------------------------
MARK_LIKE = "like"
MARK_FIX = "fix"
MARK_HIDE = "hide"
MARKS = (MARK_LIKE, MARK_FIX, MARK_HIDE)

KIND_PHOTO = "photo"
KIND_VIDEO = "video"

# ---- events ---------------------------------------------------------------------------
EVENT_SYNC_FAILED = f"{DOMAIN}_sync_failed"
EVENT_REPORT_SENT = f"{DOMAIN}_report_sent"

# Photos keep their original size; only an absurdly large picture (e.g. a huge TIFF) is scaled down to protect the display.
SAFETY_MAX_PHOTO_PX = 8192

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.state"
