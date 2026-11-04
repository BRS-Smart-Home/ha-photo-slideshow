"""Google Drive (read-only) through a service account, over plain REST.

The service account's JSON key signs a short JWT; Google answers with a one-hour access token. The integration can only see
what is shared with the service account, and only read it (scope drive.readonly).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import aiohttp
import jwt  # PyJWT, a Home Assistant dependency (RS256 signing uses `cryptography`, also in Home Assistant)

_LOGGER = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/drive.readonly"
API = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
LIST_FIELDS = (
    "nextPageToken,files(id,name,mimeType,parents,size,modifiedTime,"
    "imageMediaMetadata(time,location,cameraMake,cameraModel,width,height,rotation),"
    "videoMediaMetadata(durationMillis,width,height))"
)
PARENTS_PER_QUERY = 30


class DriveError(Exception):
    """Anything that went wrong talking to Google Drive."""


class DriveAuthError(DriveError):
    """The key is invalid, revoked, or the folder is not shared with the service account."""


class DriveNotFound(DriveError):
    """The folder or file does not exist, or it is not shared with the service account."""


@dataclass
class DriveFile:
    id: str
    parts: tuple[str, ...]            # path below the root; last = file name
    mime: str
    size: int | None
    modified: str | None
    duration_ms: int | None
    meta: dict | None                 # imageMediaMetadata


def _clean(name: str) -> str:
    return name.replace("/", "_")


class DriveClient:
    def __init__(self, session: aiohttp.ClientSession, info: dict[str, Any]) -> None:
        self._session = session
        self._email: str = info["client_email"]
        self._key: str = info["private_key"]
        self._token_uri: str = info.get("token_uri") or TOKEN_URL
        self._token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    @property
    def email(self) -> str:
        return self._email

    # ---- authentication -------------------------------------------------------------------
    def _sign(self, now: int) -> str:
        claims = {"iss": self._email, "scope": SCOPE, "aud": self._token_uri, "iat": now, "exp": now + 3600}
        return jwt.encode(claims, self._key, algorithm="RS256")

    async def _access_token(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._expires - 120:
                return self._token
            try:
                assertion = await asyncio.get_running_loop().run_in_executor(None, self._sign, int(time.time()))
            except Exception as err:  # noqa: BLE001 - bad key material
                raise DriveAuthError("The private key in the service account file could not be used") from err
            try:
                async with self._session.post(
                    self._token_uri,
                    data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status != 200:
                        raise DriveAuthError(f"Google refused the login: {data.get('error')} {data.get('error_description', '')}".strip())
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise DriveError(f"Cannot reach Google: {err}") from err
            self._token = data["access_token"]
            self._expires = time.time() + int(data.get("expires_in", 3600))
            return self._token

    # ---- requests --------------------------------------------------------------------------
    async def _get(self, url: str, params: dict | None = None, as_json: bool = True, max_bytes: int | None = None):
        last: Exception | None = None
        for attempt in range(4):
            token = await self._access_token()
            try:
                async with self._session.get(
                    url, params=params, headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=300 if not as_json else 60),
                ) as resp:
                    if resp.status == 200:
                        if as_json:
                            return await resp.json(content_type=None)
                        if max_bytes and resp.content_length and resp.content_length > max_bytes:
                            raise DriveError(f"file larger than {max_bytes} bytes")
                        return await resp.read()
                    body = (await resp.text())[:300]
                    if resp.status == 401:
                        self._token = None
                        last = DriveAuthError("Google rejected the access token")
                        continue
                    if resp.status == 404:
                        raise DriveNotFound("Not found, or not shared with the service account")
                    if resp.status == 403 and ("rateLimit" in body or "RateLimit" in body):
                        last = DriveError("Google Drive rate limit")
                        await asyncio.sleep(2 ** attempt)
                        continue
                    if resp.status == 403:
                        raise DriveAuthError(f"Access denied: {body}")
                    if resp.status in (429, 500, 502, 503, 504):
                        last = DriveError(f"HTTP {resp.status}")
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise DriveError(f"HTTP {resp.status}: {body}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last = DriveError(f"Network problem: {err}")
                await asyncio.sleep(2 ** attempt)
        raise last or DriveError("retries exhausted")

    async def get_file(self, file_id: str) -> dict:
        return await self._get(f"{API}/files/{file_id}", {"fields": "id,name,mimeType", "supportsAllDrives": "false"})

    async def download(self, file_id: str, max_bytes: int | None = None) -> bytes:
        return await self._get(f"{API}/files/{file_id}", {"alt": "media"}, as_json=False, max_bytes=max_bytes)

    async def list_tree(self, root_id: str) -> list[DriveFile]:
        """Every non-folder file below `root_id`, with its path. Raises if any part of the listing fails (never partial)."""
        paths: dict[str, tuple[str, ...]] = {root_id: ()}
        frontier = [root_id]
        out: list[DriveFile] = []
        while frontier:
            nxt: list[str] = []
            for i in range(0, len(frontier), PARENTS_PER_QUERY):
                batch = frontier[i:i + PARENTS_PER_QUERY]
                batch_set = set(batch)
                q = "(" + " or ".join(f"'{p}' in parents" for p in batch) + ") and trashed=false"
                page: str | None = None
                while True:
                    params = {"q": q, "pageSize": 1000, "fields": LIST_FIELDS, "supportsAllDrives": "false"}
                    if page:
                        params["pageToken"] = page
                    data = await self._get(f"{API}/files", params)
                    for f in data.get("files", []):
                        parent = next((p for p in f.get("parents", []) if p in batch_set), None)
                        if parent is None:
                            continue
                        name = _clean(f.get("name", ""))
                        if f.get("mimeType") == FOLDER_MIME:
                            paths[f["id"]] = paths[parent] + (name,)
                            nxt.append(f["id"])
                            continue
                        if str(f.get("mimeType", "")).startswith("application/vnd.google-apps."):
                            continue                                   # Docs, Sheets, shortcuts ...
                        vm = f.get("videoMediaMetadata") or {}
                        dur = vm.get("durationMillis")
                        size = f.get("size")
                        out.append(DriveFile(
                            id=f["id"], parts=paths[parent] + (name,), mime=f.get("mimeType", ""),
                            size=int(size) if size is not None else None, modified=f.get("modifiedTime"),
                            duration_ms=int(dur) if dur is not None else None, meta=f.get("imageMediaMetadata"),
                        ))
                    page = data.get("nextPageToken")
                    if not page:
                        break
            frontier = nxt
        return out
