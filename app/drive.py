"""Per-user Google Drive storage. The app only sees files it created."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from base64 import urlsafe_b64encode
from pathlib import Path

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

log = logging.getLogger("engineering_assistant.drive")

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
ROOT_FOLDER = "EAIA"
GENERAL_FOLDER = "General Codes and STD"
STANDARDS_FOLDER = "Codes & Standards"
PROJECT_FOLDER = "Project documents"
GLOBAL_FOLDER = "Global knowledge"
_STATE_TTL = 600


class DriveError(Exception):
    pass


class DriveClient:
    """Small Drive client. Tests replace client_for_token with a fake."""

    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token
        self._access = ""

    def access_token(self) -> str:
        if self._access:
            return self._access
        settings = get_settings()
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise DriveError(f"Drive token refresh failed: HTTP {response.status_code}")
        self._access = response.json().get("access_token") or ""
        if not self._access:
            raise DriveError("Drive token refresh returned no access token")
        return self._access

    def put_in_folders(self, folders: list[str], filename: str, data: bytes, mime: str) -> str:
        parent = self._ensure_folders(folders)
        boundary = hashlib.sha256(filename.encode()).hexdigest()[:24]
        metadata = json.dumps({"name": filename, "parents": [parent]})
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
            f"--{boundary}\r\nContent-Type: {mime or 'application/octet-stream'}\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--".encode()
        response = httpx.post(
            "https://www.googleapis.com/upload/drive/v3/files",
            params={"uploadType": "multipart", "fields": "id"},
            headers={
                "Authorization": f"Bearer {self.access_token()}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            content=body,
            timeout=60,
        )
        if response.status_code >= 400:
            raise DriveError(f"Drive upload failed: HTTP {response.status_code}")
        file_id = response.json().get("id") or ""
        if not file_id:
            raise DriveError("Drive upload returned no file id")
        return file_id

    def delete(self, file_id: str) -> None:
        response = httpx.delete(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers={"Authorization": f"Bearer {self.access_token()}"},
            timeout=30,
        )
        if response.status_code in {200, 204, 404}:
            return
        raise DriveError(f"Drive delete failed: HTTP {response.status_code}")

    def exists(self, file_id: str) -> bool:
        response = httpx.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"fields": "id,trashed"},
            headers={"Authorization": f"Bearer {self.access_token()}"},
            timeout=20,
        )
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise DriveError(f"Drive lookup failed: HTTP {response.status_code}")
        return not bool(response.json().get("trashed"))

    def _ensure_folders(self, names: list[str]) -> str:
        parent = ""
        for name in names:
            parent = self._folder(name, parent)
        return parent

    def _folder(self, name: str, parent: str) -> str:
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"name = '{escaped}' and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )
        if parent:
            query += f" and '{parent}' in parents"
        response = httpx.get(
            "https://www.googleapis.com/drive/v3/files",
            params={"q": query, "fields": "files(id)", "pageSize": 1, "spaces": "drive"},
            headers={"Authorization": f"Bearer {self.access_token()}"},
            timeout=20,
        )
        if response.status_code >= 400:
            raise DriveError(f"Drive folder lookup failed: HTTP {response.status_code}")
        found = response.json().get("files") or []
        if found:
            return found[0]["id"]
        metadata: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent:
            metadata["parents"] = [parent]
        created = httpx.post(
            "https://www.googleapis.com/drive/v3/files",
            params={"fields": "id"},
            headers={"Authorization": f"Bearer {self.access_token()}"},
            json=metadata,
            timeout=20,
        )
        if created.status_code >= 400:
            raise DriveError(f"Drive folder create failed: HTTP {created.status_code}")
        return created.json()["id"]

    def ensure_path(self, folders: list[str]) -> str:
        return self._ensure_folders(folders)

    def relocate(self, file_id: str, folders: list[str]) -> str:
        """Move a file the app created into another folder path (addParents/removeParents)."""
        parent = self._ensure_folders(folders)
        current_response = httpx.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"fields": "parents"},
            headers={"Authorization": f"Bearer {self.access_token()}"},
            timeout=20,
        )
        if current_response.status_code >= 400:
            raise DriveError(f"Drive parent lookup failed: HTTP {current_response.status_code}")
        current = current_response.json().get("parents") or []
        if current == [parent]:
            return parent
        params = {"addParents": parent, "fields": "id,parents"}
        if current:
            params["removeParents"] = ",".join(current)
        moved = httpx.patch(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params=params,
            headers={"Authorization": f"Bearer {self.access_token()}"},
            timeout=30,
        )
        if moved.status_code >= 400:
            raise DriveError(f"Drive move failed: HTTP {moved.status_code}")
        return parent

    def rename(self, file_id: str, name: str) -> None:
        response = httpx.patch(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers={"Authorization": f"Bearer {self.access_token()}"},
            json={"name": name},
            timeout=20,
        )
        if response.status_code >= 400:
            raise DriveError(f"Drive rename failed: HTTP {response.status_code}")


def client_for_token(refresh_token: str) -> DriveClient:
    return DriveClient(refresh_token)


def _fernet() -> Fernet:
    settings = get_settings()
    material = settings.token_enc_key or settings.secret_key or "dev-secret-change-me"
    key = urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_token(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_token(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        log.warning("Could not read a stored Drive token")
        return ""


def authorization_url(user_id: str) -> str:
    settings = get_settings()
    if not settings.google_configured:
        raise DriveError("Google Drive is not configured")
    query = httpx.QueryParams(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": f"{settings.public_base_url}/api/drive/callback",
            "response_type": "code",
            "scope": DRIVE_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": sign_state(user_id),
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def sign_state(user_id: str) -> str:
    payload = f"{user_id}.{int(time.time())}"
    secret = (get_settings().token_enc_key or get_settings().secret_key).encode("utf-8")
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_state(state: str) -> str:
    parts = (state or "").split(".")
    if len(parts) != 3:
        raise DriveError("Drive sign-in state is not valid")
    user_id, issued, sig = parts
    payload = f"{user_id}.{issued}"
    secret = (get_settings().token_enc_key or get_settings().secret_key).encode("utf-8")
    expected = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise DriveError("Drive sign-in state is not valid")
    try:
        age = int(time.time()) - int(issued)
    except ValueError as exc:
        raise DriveError("Drive sign-in state is not valid") from exc
    if age < 0 or age > _STATE_TTL:
        raise DriveError("Drive sign-in state expired")
    return user_id


def exchange_code(code: str) -> str:
    settings = get_settings()
    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": f"{settings.public_base_url}/api/drive/callback",
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise DriveError(f"Drive authorization failed: HTTP {response.status_code}")
    refresh = response.json().get("refresh_token") or ""
    if not refresh:
        raise DriveError("Google did not return a refresh token. Connect again and approve offline access.")
    return refresh


def revoke_token(refresh_token: str) -> None:
    if not refresh_token:
        return
    try:
        httpx.post("https://oauth2.googleapis.com/revoke", data={"token": refresh_token}, timeout=20)
    except httpx.HTTPError as exc:
        log.warning("Drive revoke failed: %s", type(exc).__name__)


def section_folder(doc_type: str, scope: str) -> str:
    if scope == "global":
        return GLOBAL_FOLDER
    if scope == "personal":
        return GENERAL_FOLDER
    if doc_type == "standard":
        return STANDARDS_FOLDER
    return ""


def write_local_copy(data: bytes, filename: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / Path(filename).name
    target.write_bytes(data)
    return target
