"""Setup and options screens."""
from __future__ import annotations

import json
import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_OUTPUT_DIR,
    CONF_ROOT_FOLDER_ID,
    CONF_SERVICE_ACCOUNT,
    DEFAULT_OPTIONS,
    DOMAIN,
    NAME,
    OPT_EXCLUDE_FILES,
    OPT_EXCLUDE_FOLDERS,
    OPT_FAILS_BEFORE_PUSH,
    OPT_INCLUDE_FOLDERS,
    OPT_MAX_PHOTO_PX,
    OPT_MAX_VIDEO_MB,
    OPT_MAX_VIDEO_SECONDS,
    OPT_NEW_BOOST_DAYS,
    OPT_NEW_BOOST_WEIGHT,
    OPT_PHOTOS_PER_DAY,
    OPT_PHOTO_FORMATS,
    OPT_REPORT_NOTIFY,
    OPT_REPORT_TIME,
    OPT_SCAN_TIME,
    OPT_SCAN_WEEKDAY,
    OPT_SYNC_TIME,
    OPT_VIDEOS_PER_DAY,
    OPT_VIDEO_FORMATS,
)
from .drive import DriveAuthError, DriveClient, DriveError, DriveNotFound, FOLDER_MIME

_FOLDER_ID = re.compile(r"[A-Za-z0-9_-]{10,}")


def _extract_folder_id(text: str) -> str:
    """Accept a bare id or a Drive folder URL (…/folders/<id>?…)."""
    text = text.strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", text)
    return m.group(1) if m else text


class TravelSlideshowConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TravelSlideshowOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        user_input = user_input or {}
        if user_input:
            root_id = _extract_folder_id(user_input[CONF_ROOT_FOLDER_ID])
            try:
                info = json.loads(user_input[CONF_SERVICE_ACCOUNT])
                if not isinstance(info, dict):
                    raise ValueError
            except ValueError:
                errors[CONF_SERVICE_ACCOUNT] = "invalid_json"
            else:
                if info.get("type") != "service_account" or not info.get("client_email") or not info.get("private_key"):
                    errors[CONF_SERVICE_ACCOUNT] = "invalid_key"
                elif not _FOLDER_ID.fullmatch(root_id):
                    errors[CONF_ROOT_FOLDER_ID] = "invalid_folder_id"
                else:
                    client = DriveClient(async_get_clientsession(self.hass), info)
                    try:
                        meta = await client.get_file(root_id)
                    except DriveAuthError:
                        errors["base"] = "auth_failed"
                    except DriveNotFound:
                        errors[CONF_ROOT_FOLDER_ID] = "folder_not_found"
                    except DriveError:
                        errors["base"] = "cannot_connect"
                    else:
                        if meta.get("mimeType") != FOLDER_MIME:
                            errors[CONF_ROOT_FOLDER_ID] = "not_a_folder"
                        else:
                            await self.async_set_unique_id(root_id)
                            self._abort_if_unique_id_configured()
                            return self.async_create_entry(
                                title=f"{NAME} ({meta.get('name', 'Drive')})",
                                data={
                                    CONF_SERVICE_ACCOUNT: json.dumps(info),
                                    CONF_ROOT_FOLDER_ID: root_id,
                                    CONF_OUTPUT_DIR: user_input[CONF_OUTPUT_DIR].strip(),
                                },
                            )
        schema = vol.Schema({
            vol.Required(CONF_SERVICE_ACCOUNT, default=user_input.get(CONF_SERVICE_ACCOUNT, "")): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)),
            vol.Required(CONF_ROOT_FOLDER_ID, default=user_input.get(CONF_ROOT_FOLDER_ID, "")): selector.TextSelector(),
            vol.Required(CONF_OUTPUT_DIR, default=user_input.get(CONF_OUTPUT_DIR, self.hass.config.path("www/slideshow"))): selector.TextSelector(),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


# ---- options: lists are edited as one entry per line --------------------------------------------------------
def _lines(value: list[str]) -> str:
    return "\n".join(value)


def _parse_lines(text: str) -> list[str]:
    return [ln.strip() for ln in str(text).splitlines() if ln.strip()]


def _parse_formats(text: str) -> list[str]:
    return [t.lower().lstrip(".") for t in re.split(r"[\s,;]+", str(text)) if t.strip(". ")]


def _num(min_: float, max_: float, step: float = 1, unit: str | None = None) -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(
        min=min_, max=max_, step=step, mode=selector.NumberSelectorMode.BOX, unit_of_measurement=unit))


_TEXT_BOX = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
_WEEKDAYS = selector.SelectSelector(selector.SelectSelectorConfig(
    options=[{"value": str(i), "label": n} for i, n in enumerate(
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])],
    mode=selector.SelectSelectorMode.DROPDOWN))


class TravelSlideshowOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        cur = {**DEFAULT_OPTIONS, **self.config_entry.options}
        if user_input is not None:
            out = {
                OPT_PHOTOS_PER_DAY: int(user_input[OPT_PHOTOS_PER_DAY]),
                OPT_VIDEOS_PER_DAY: int(user_input[OPT_VIDEOS_PER_DAY]),
                OPT_MAX_PHOTO_PX: int(user_input[OPT_MAX_PHOTO_PX]),
                OPT_MAX_VIDEO_SECONDS: int(user_input[OPT_MAX_VIDEO_SECONDS]),
                OPT_MAX_VIDEO_MB: int(user_input[OPT_MAX_VIDEO_MB]),
                OPT_INCLUDE_FOLDERS: _parse_lines(user_input[OPT_INCLUDE_FOLDERS]) or ["*"],
                OPT_EXCLUDE_FOLDERS: _parse_lines(user_input[OPT_EXCLUDE_FOLDERS]),
                OPT_EXCLUDE_FILES: _parse_lines(user_input[OPT_EXCLUDE_FILES]),
                OPT_PHOTO_FORMATS: _parse_formats(user_input[OPT_PHOTO_FORMATS]),
                OPT_VIDEO_FORMATS: _parse_formats(user_input[OPT_VIDEO_FORMATS]),
                OPT_SYNC_TIME: user_input[OPT_SYNC_TIME],
                OPT_SCAN_WEEKDAY: int(user_input[OPT_SCAN_WEEKDAY]),
                OPT_SCAN_TIME: user_input[OPT_SCAN_TIME],
                OPT_REPORT_TIME: user_input[OPT_REPORT_TIME],
                OPT_REPORT_NOTIFY: _parse_lines(user_input[OPT_REPORT_NOTIFY]),
                OPT_NEW_BOOST_DAYS: int(user_input[OPT_NEW_BOOST_DAYS]),
                OPT_NEW_BOOST_WEIGHT: float(user_input[OPT_NEW_BOOST_WEIGHT]),
                OPT_FAILS_BEFORE_PUSH: int(user_input[OPT_FAILS_BEFORE_PUSH]),
            }
            return self.async_create_entry(data=out)
        schema = vol.Schema({
            vol.Required(OPT_PHOTOS_PER_DAY, default=cur[OPT_PHOTOS_PER_DAY]): _num(0, 500),
            vol.Required(OPT_VIDEOS_PER_DAY, default=cur[OPT_VIDEOS_PER_DAY]): _num(0, 100),
            vol.Required(OPT_MAX_PHOTO_PX, default=cur[OPT_MAX_PHOTO_PX]): _num(256, 4096, 64, "px"),
            vol.Required(OPT_MAX_VIDEO_SECONDS, default=cur[OPT_MAX_VIDEO_SECONDS]): _num(1, 600, 1, "s"),
            vol.Required(OPT_MAX_VIDEO_MB, default=cur[OPT_MAX_VIDEO_MB]): _num(1, 2000, 1, "MB"),
            vol.Required(OPT_INCLUDE_FOLDERS, default=_lines(cur[OPT_INCLUDE_FOLDERS])): _TEXT_BOX,
            vol.Required(OPT_EXCLUDE_FOLDERS, default=_lines(cur[OPT_EXCLUDE_FOLDERS])): _TEXT_BOX,
            vol.Required(OPT_EXCLUDE_FILES, default=_lines(cur[OPT_EXCLUDE_FILES])): _TEXT_BOX,
            vol.Required(OPT_PHOTO_FORMATS, default=" ".join(cur[OPT_PHOTO_FORMATS])): selector.TextSelector(),
            vol.Required(OPT_VIDEO_FORMATS, default=" ".join(cur[OPT_VIDEO_FORMATS])): selector.TextSelector(),
            vol.Required(OPT_SYNC_TIME, default=cur[OPT_SYNC_TIME]): selector.TimeSelector(),
            vol.Required(OPT_SCAN_WEEKDAY, default=str(cur[OPT_SCAN_WEEKDAY])): _WEEKDAYS,
            vol.Required(OPT_SCAN_TIME, default=cur[OPT_SCAN_TIME]): selector.TimeSelector(),
            vol.Required(OPT_REPORT_TIME, default=cur[OPT_REPORT_TIME]): selector.TimeSelector(),
            vol.Required(OPT_REPORT_NOTIFY, default=_lines(cur[OPT_REPORT_NOTIFY])): _TEXT_BOX,
            vol.Required(OPT_NEW_BOOST_DAYS, default=cur[OPT_NEW_BOOST_DAYS]): _num(0, 90, 1, "days"),
            vol.Required(OPT_NEW_BOOST_WEIGHT, default=cur[OPT_NEW_BOOST_WEIGHT]): _num(1, 20, 0.5),
            vol.Required(OPT_FAILS_BEFORE_PUSH, default=cur[OPT_FAILS_BEFORE_PUSH]): _num(1, 10),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
