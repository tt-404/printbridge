"""WebDAV provider — covers Nextcloud, ownCloud, many NAS and mailbox.org etc.

The friendliest home-user cloud: no developer app registration, just a server
URL, a username and an app-password (Basic auth over HTTPS). Credentials are
entered in the web UI and stored in the data directory.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree as ET

import httpx

from ..config import data_dir
from .base import Folder, IncomingFile, LinkState, Provider, ProviderStatus, register

_DAV = "{DAV:}"


def _parse_children(content: bytes, self_path: str) -> list[tuple[str, bool]]:
    """Parse a PROPFIND (Depth:1) multistatus into (name, is_folder) pairs,
    excluding the queried folder itself."""
    root = ET.fromstring(content)
    self_path = self_path.rstrip("/")
    out: list[tuple[str, bool]] = []
    for r in root.findall(f"{_DAV}response"):
        href_path = urlsplit(r.findtext(f"{_DAV}href") or "").path.rstrip("/")
        if not href_path or href_path == self_path:
            continue
        name = unquote(href_path.rsplit("/", 1)[-1])
        is_folder = r.find(f".//{_DAV}collection") is not None
        out.append((name, is_folder))
    return out


class WebDAVProvider:
    key = "webdav"
    label = "WebDAV / Nextcloud"
    experimental = False
    supports_incoming = True
    supports_browse = True
    # Rendered as a form in the UI; filled values are passed to configure().
    credential_fields = [
        {"name": "url", "label": "Server-URL (WebDAV)", "type": "url",
         "placeholder": "https://cloud.example.com/remote.php/dav/files/BENUTZER/"},
        {"name": "username", "label": "Benutzername"},
        {"name": "password", "label": "App-Passwort", "type": "password"},
    ]

    def __init__(self, upload_folder: str = "/PrintBridge",
                 print_folder: str = "/PrintBridge/ToPrint") -> None:
        self.upload_folder = "/" + upload_folder.strip("/")
        self.print_folder = "/" + print_folder.strip("/")
        self._cred_file = data_dir() / "webdav_cred.json"

    # --- credentials -------------------------------------------------------
    def _creds(self) -> dict | None:
        if self._cred_file.exists():
            return json.loads(self._cred_file.read_text())
        return None

    def _client(self) -> httpx.Client:
        c = self._creds()
        if not c:
            raise RuntimeError("WebDAV is not configured.")
        return httpx.Client(auth=(c["username"], c["password"]), timeout=60,
                            follow_redirects=True)

    def _base(self) -> str:
        return self._creds()["url"].rstrip("/")

    def _url(self, path: str) -> str:
        # Each path segment is URL-encoded; the base already points at the user's root.
        segs = [quote(s) for s in path.strip("/").split("/") if s]
        return self._base() + ("/" + "/".join(segs) if segs else "")

    # --- configure / status ------------------------------------------------
    def configure(self, url: str = "", username: str = "", password: str = "") -> ProviderStatus:
        url = url.strip()
        if not (url and username and password):
            return ProviderStatus(LinkState.UNLINKED, "URL, Benutzer und Passwort angeben.")
        # Verify with a PROPFIND against the given root before saving.
        try:
            resp = httpx.request(
                "PROPFIND", url.rstrip("/"), auth=(username, password),
                headers={"Depth": "0"}, timeout=30, follow_redirects=True,
            )
        except Exception as exc:
            return ProviderStatus(LinkState.UNLINKED, f"Verbindung fehlgeschlagen: {exc}")
        if resp.status_code in (401, 403):
            return ProviderStatus(LinkState.UNLINKED, "Anmeldung abgelehnt (Benutzer/Passwort?).")
        if resp.status_code >= 400:
            return ProviderStatus(LinkState.UNLINKED, f"Server-Antwort HTTP {resp.status_code}.")
        self._cred_file.write_text(json.dumps({"url": url, "username": username,
                                               "password": password}))
        self._cred_file.chmod(0o600)
        return ProviderStatus(LinkState.LINKED, "WebDAV verbunden.")

    def status(self) -> ProviderStatus:
        if not self._creds():
            return ProviderStatus(LinkState.UNLINKED, "Nicht konfiguriert.")
        return ProviderStatus(LinkState.LINKED, "WebDAV verbunden.")

    def begin_link(self) -> ProviderStatus:
        return self.status()

    def poll_link(self) -> ProviderStatus:
        return self.status()

    def unlink(self) -> None:
        self._cred_file.unlink(missing_ok=True)

    # --- helpers -----------------------------------------------------------
    def _ensure_folder(self, client: httpx.Client, path: str) -> None:
        # MKCOL each level; 405/301 mean it already exists, which is fine.
        parts = [p for p in path.strip("/").split("/") if p]
        for i in range(1, len(parts) + 1):
            sub = "/".join(parts[:i])
            client.request("MKCOL", self._url(sub))

    def _propfind(self, folder: str) -> list[tuple[str, bool]]:
        """Return (name, is_folder) for the direct children of folder."""
        with self._client() as client:
            resp = client.request("PROPFIND", self._url(folder), headers={"Depth": "1"})
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return _parse_children(resp.content, urlsplit(self._url(folder)).path)

    # --- upload / browse / incoming ---------------------------------------
    def upload(self, filename: str, data: bytes) -> None:
        with self._client() as client:
            self._ensure_folder(client, self.upload_folder)
            resp = client.put(self._url(f"{self.upload_folder}/{filename}"), content=data)
            if resp.status_code >= 400:
                raise RuntimeError(f"WebDAV upload failed: HTTP {resp.status_code}")

    def browse_root(self) -> str:
        return ""

    def list_folders(self, path: str) -> list[Folder]:
        base = path.rstrip("/")
        return [Folder(name=n, path=f"{base}/{n}")
                for n, is_dir in self._propfind(path) if is_dir]

    def list_incoming(self) -> list[IncomingFile]:
        base = self.print_folder.rstrip("/")
        return [IncomingFile(id=f"{base}/{n}", name=n)
                for n, is_dir in self._propfind(self.print_folder) if not is_dir]

    def download(self, file_id: str) -> bytes:
        with self._client() as client:
            resp = client.get(self._url(file_id))
            resp.raise_for_status()
            return resp.content


@register("webdav")
def _factory(**kwargs) -> Provider:
    return WebDAVProvider(**kwargs)
