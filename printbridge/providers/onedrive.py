"""OneDrive provider via Microsoft Graph, using the OAuth device-code flow.

Device-code flow fits a headless Pi: the web UI shows a short code, the user
confirms it once at microsoft.com/devicelogin in any browser, and from then on
everything happens in the UI. No client secret is needed (public client), which
is why this can ship in a public repo — only a non-secret client_id is required,
from the user's own Azure app registration (see README).

NOTE: the Graph HTTP calls below are written against the documented API but have
NOT been exercised against a live Microsoft account in this environment. Treat
first real sign-in as the integration test.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import data_dir
from .base import Folder, IncomingFile, LinkState, Provider, ProviderStatus, register

_AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0"
_GRAPH = "https://graph.microsoft.com/v1.0"
_SCOPE = "Files.ReadWrite offline_access"


class OneDriveProvider:
    key = "onedrive"
    label = "OneDrive"
    experimental = False
    supports_incoming = True
    supports_browse = True

    def __init__(self, client_id: str = "", upload_folder: str = "/PrintBridge",
                 print_folder: str = "/PrintBridge/ToPrint") -> None:
        self.client_id = client_id
        self.upload_folder = "/" + upload_folder.strip("/")
        self.print_folder = "/" + print_folder.strip("/")
        self._token_file = data_dir() / "onedrive_token.json"
        # Transient device-code state for a link in progress.
        self._pending: dict[str, Any] | None = None

    # --- token persistence -------------------------------------------------
    def _load_token(self) -> dict[str, Any] | None:
        if self._token_file.exists():
            return json.loads(self._token_file.read_text())
        return None

    def _save_token(self, tok: dict[str, Any]) -> None:
        tok["obtained_at"] = int(time.time())
        self._token_file.write_text(json.dumps(tok))
        self._token_file.chmod(0o600)

    # --- status ------------------------------------------------------------
    def status(self) -> ProviderStatus:
        if not self.client_id:
            return ProviderStatus(
                LinkState.UNLINKED,
                "Set a Microsoft client_id (Azure app registration) to enable OneDrive.",
            )
        if self._pending:
            return ProviderStatus(
                LinkState.PENDING,
                "Confirm the code to finish connecting OneDrive.",
                user_code=self._pending.get("user_code"),
                verification_url=self._pending.get("verification_uri"),
            )
        if self._load_token():
            return ProviderStatus(LinkState.LINKED, "OneDrive connected.")
        return ProviderStatus(LinkState.UNLINKED, "OneDrive not connected.")

    # --- linking -----------------------------------------------------------
    def begin_link(self) -> ProviderStatus:
        if not self.client_id:
            return self.status()
        resp = httpx.post(
            f"{_AUTHORITY}/devicecode",
            data={"client_id": self.client_id, "scope": _SCOPE},
            timeout=30,
        )
        resp.raise_for_status()
        self._pending = resp.json()
        return self.status()

    def poll_link(self) -> ProviderStatus:
        if not self._pending:
            return self.status()
        resp = httpx.post(
            f"{_AUTHORITY}/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.client_id,
                "device_code": self._pending["device_code"],
            },
            timeout=30,
        )
        if resp.status_code == 200:
            self._save_token(resp.json())
            self._pending = None
            return ProviderStatus(LinkState.LINKED, "OneDrive connected.")
        # authorization_pending is normal until the user confirms the code.
        err = resp.json().get("error", "")
        if err == "authorization_pending":
            return self.status()
        self._pending = None
        return ProviderStatus(LinkState.UNLINKED, f"Linking failed: {err or resp.text}")

    def unlink(self) -> None:
        self._pending = None
        self._token_file.unlink(missing_ok=True)

    # --- access token ------------------------------------------------------
    def _access_token(self) -> str:
        tok = self._load_token()
        if not tok:
            raise RuntimeError("OneDrive is not connected.")
        # Refresh a little early. Graph tokens last ~3600s.
        age = int(time.time()) - int(tok.get("obtained_at", 0))
        if age < int(tok.get("expires_in", 3600)) - 120:
            return tok["access_token"]
        resp = httpx.post(
            f"{_AUTHORITY}/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": tok["refresh_token"],
                "scope": _SCOPE,
            },
            timeout=30,
        )
        resp.raise_for_status()
        new = resp.json()
        # Microsoft may omit a new refresh_token; keep the old one if so.
        new.setdefault("refresh_token", tok["refresh_token"])
        self._save_token(new)
        return new["access_token"]

    # --- upload ------------------------------------------------------------
    def upload(self, filename: str, data: bytes) -> None:
        token = self._access_token()
        path = f"{self.upload_folder}/{filename}".lstrip("/")
        url = f"{_GRAPH}/me/drive/root:/{path}:/content"
        resp = httpx.put(
            url,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/octet-stream"},
            content=data,
            timeout=120,
        )
        resp.raise_for_status()

    # --- incoming (Cloud -> Print) -----------------------------------------
    def list_incoming(self) -> list[IncomingFile]:
        token = self._access_token()
        path = self.print_folder.lstrip("/")
        url = f"{_GRAPH}/me/drive/root:/{path}:/children"
        resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if resp.status_code == 404:
            return []  # folder not created yet -> nothing to print
        resp.raise_for_status()
        out: list[IncomingFile] = []
        for item in resp.json().get("value", []):
            if "file" in item:  # skip sub-folders
                out.append(IncomingFile(id=item["id"], name=item["name"]))
        return out

    def download(self, file_id: str) -> bytes:
        token = self._access_token()
        url = f"{_GRAPH}/me/drive/items/{file_id}/content"
        resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"},
                         timeout=120, follow_redirects=True)
        resp.raise_for_status()
        return resp.content

    # --- folder browser ----------------------------------------------------
    def browse_root(self) -> str:
        return ""  # OneDrive drive root

    def list_folders(self, path: str) -> list[Folder]:
        token = self._access_token()
        rel = path.strip("/")
        if rel:
            url = f"{_GRAPH}/me/drive/root:/{rel}:/children"
        else:
            url = f"{_GRAPH}/me/drive/root/children"
        resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"},
                         params={"$select": "name,folder", "$top": "200"}, timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        out: list[Folder] = []
        for item in resp.json().get("value", []):
            if "folder" in item:
                name = item["name"]
                full = f"/{rel}/{name}" if rel else f"/{name}"
                out.append(Folder(name=name, path=full))
        return out


@register("onedrive")
def _factory(**kwargs) -> Provider:
    return OneDriveProvider(**kwargs)
