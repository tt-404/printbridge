"""Proton Drive provider via the official `proton-drive` CLI.

Proton shipped an official Proton Drive CLI (single binary, Windows/macOS/Linux)
that logs in through the browser and keeps the session in the OS keychain. We
drive it as a subprocess — the one external tool this project relies on, and
only for Proton, which Proton itself positions as the supported way to script
Drive.

Auth: the user runs `proton-drive auth login` once in a terminal (it opens a
browser; no password touches this app). We never handle Proton credentials.

Documented commands used (from Proton's announcement):
    proton-drive auth login
    proton-drive filesystem upload <file> <folder>
    proton-drive filesystem list <folder> --json
    proton-drive filesystem download <remote_path> <local_dir>

CAVEAT: the exact JSON shape of `filesystem list --json` is not documented in
the announcement, so `_parse_list_json` parses it tolerantly and MUST be
verified against your installed CLI. Everything else uses documented commands.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import Folder, IncomingFile, LinkState, Provider, ProviderStatus, register

_PROBE_TTL = 30.0  # seconds to cache the auth probe so the dashboard stays fast


def _iter_items(stdout: str):
    """Yield entries from `filesystem list --json`, tolerant of the wrapper."""
    data = json.loads(stdout)
    if isinstance(data, list):
        return [it for it in data if isinstance(it, dict)]
    if isinstance(data, dict):
        lst = next((v for v in data.values() if isinstance(v, list)), [])
        return [it for it in lst if isinstance(it, dict)]
    return []


def _is_folder(it: dict) -> bool:
    type_str = str(it.get("type", "")).lower()
    return type_str in ("folder", "dir", "directory") or it.get("isFolder") is True


def _name_of(it: dict) -> str | None:
    name = it.get("name")
    # Proton wraps field values as {"ok": true, "value": "<name>"}.
    if isinstance(name, dict):
        name = name.get("value")
    if not name:
        name = it.get("filename") or it.get("path")
    return str(name).rstrip("/").split("/")[-1] if name else None


def _parse_list_json(stdout: str, folder: str) -> list[IncomingFile]:
    """Turn `filesystem list --json` output into incoming files (folders skipped).

    Tolerant on purpose: accepts either a top-level list or a dict wrapping a
    list, and tries several common field names. VERIFY against the real CLI.
    """
    base = folder.rstrip("/")
    out: list[IncomingFile] = []
    for it in _iter_items(stdout):
        if _is_folder(it):
            continue
        name = _name_of(it)
        if name:
            out.append(IncomingFile(id=f"{base}/{name}", name=name))
    return out


def _parse_folders_json(stdout: str, folder: str) -> list[Folder]:
    """Sub-folders from `filesystem list --json` (files excluded)."""
    base = folder.rstrip("/")
    out: list[Folder] = []
    for it in _iter_items(stdout):
        if not _is_folder(it):
            continue
        name = _name_of(it)
        if name:
            out.append(Folder(name=name, path=f"{base}/{name}"))
    return out


class ProtonDriveProvider:
    key = "protondrive"
    label = "Proton Drive"
    experimental = True
    supports_incoming = True
    supports_browse = True

    def __init__(self, binary: str = "proton-drive",
                 root: str = "/my-files",
                 upload_folder: str = "/my-files/PrintBridge",
                 print_folder: str = "/my-files/PrintBridge/ToPrint") -> None:
        self.binary = binary
        self.root = root
        self.upload_folder = upload_folder
        self.print_folder = print_folder
        self._probe: tuple[float, LinkState] | None = None

    # --- subprocess helper -------------------------------------------------
    def _exe(self) -> str | None:
        return shutil.which(self.binary) or (self.binary if Path(self.binary).exists() else None)

    def _run(self, args: list[str], *, timeout: float = 60.0,
             text: bool = True) -> subprocess.CompletedProcess:
        exe = self._exe()
        if not exe:
            raise RuntimeError("proton-drive CLI not found. Install it and set it on PATH.")
        return subprocess.run([exe, *args], capture_output=True, text=text, timeout=timeout)

    # --- status ------------------------------------------------------------
    def status(self) -> ProviderStatus:
        if not self._exe():
            return ProviderStatus(
                LinkState.UNAVAILABLE,
                "proton-drive CLI not installed. Download it from Proton and put it on PATH.",
            )
        state = self._auth_state()
        if state is LinkState.LINKED:
            return ProviderStatus(LinkState.LINKED, "Proton Drive connected.")
        return ProviderStatus(
            LinkState.UNLINKED,
            "Run `proton-drive auth login` in a terminal once, then click Verbinden.",
        )

    def _auth_state(self) -> LinkState:
        now = time.time()
        if self._probe and now - self._probe[0] < _PROBE_TTL:
            return self._probe[1]
        try:
            proc = self._run(["filesystem", "list", self.root, "--json"], timeout=25)
            state = LinkState.LINKED if proc.returncode == 0 else LinkState.UNLINKED
        except Exception:
            state = LinkState.UNLINKED
        self._probe = (now, state)
        return state

    # --- linking -----------------------------------------------------------
    def begin_link(self) -> ProviderStatus:
        # The browser login is interactive; it is run by the user in a terminal.
        # Clicking Verbinden just re-checks whether that login has happened.
        self._probe = None
        return self.status()

    def poll_link(self) -> ProviderStatus:
        self._probe = None
        return self.status()

    def unlink(self) -> None:
        self._probe = None
        try:
            self._run(["auth", "logout"], timeout=30)
        except Exception:
            pass

    # --- upload (Scan -> Proton) -------------------------------------------
    def upload(self, filename: str, data: bytes) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / filename
            local.write_bytes(data)
            # -f rename / -t keep the upload fully non-interactive: without a
            # conflict strategy the CLI PROMPTS and would hang in the daemon.
            # 'rename' never drops a scan; 't' skips thumbnail generation.
            proc = self._run(
                ["filesystem", "upload", "-f", "rename", "-t",
                 str(local), self.upload_folder],
                timeout=300,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"proton-drive upload failed: {proc.stderr.strip()}")

    # --- incoming (Cloud -> Print) -----------------------------------------
    def list_incoming(self) -> list[IncomingFile]:
        proc = self._run(["filesystem", "list", self.print_folder, "--json"], timeout=60)
        if proc.returncode != 0:
            # Most likely the folder does not exist yet -> nothing to print.
            return []
        return _parse_list_json(proc.stdout, self.print_folder)

    def download(self, file_id: str) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(["filesystem", "download", file_id, tmp], timeout=300)
            if proc.returncode != 0:
                raise RuntimeError(f"proton-drive download failed: {proc.stderr.strip()}")
            files = [p for p in Path(tmp).iterdir() if p.is_file()]
            if not files:
                raise RuntimeError("proton-drive download produced no file")
            return files[0].read_bytes()

    # --- folder browser ----------------------------------------------------
    def browse_root(self) -> str:
        return self.root

    def list_folders(self, path: str) -> list[Folder]:
        proc = self._run(["filesystem", "list", path, "--json"], timeout=60)
        if proc.returncode != 0:
            return []
        return _parse_folders_json(proc.stdout, path)


@register("protondrive")
def _factory(**kwargs) -> Provider:
    return ProtonDriveProvider(**kwargs)
