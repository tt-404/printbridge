"""Application core: wires the printer, scanner, providers and activity log.

The web layer calls into this and nothing else, so the business logic stays
testable without a running web server.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import providers as provider_pkg
from .config import Config
from .db import ActivityLog
from .printer import Printer
from .providers.base import LinkState, Provider
from .scanner import Scanner, ScanSettings

log = logging.getLogger("printbridge")
_AUTOPRINT_KEY = "autoprint_enabled"


class Core:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.log = ActivityLog(config.database_path)
        self.scanner = Scanner(config.printer.host, config.printer.escl_path)
        self.printer = Printer(config.printer.host)
        self._providers: dict[str, Provider] = {}
        # (service, item_id) pairs we have already logged as failed, so a file
        # that keeps failing does not spam the activity log every poll.
        self._failed_logged: set[tuple[str, str]] = set()
        self._build_providers()
        self._apply_folder_overrides()

    def _build_providers(self) -> None:
        """Instantiate every registered provider, passing its config block."""
        for key in provider_pkg.available_keys():
            opts = dict(self.config.services.get(key, {}))
            opts.pop("enabled", None)  # not a constructor arg
            try:
                self._providers[key] = provider_pkg.create(key, **opts)
            except TypeError:
                # Provider takes no/other kwargs; create bare.
                self._providers[key] = provider_pkg.create(key)

    @property
    def providers(self) -> dict[str, Provider]:
        return self._providers

    def provider(self, key: str) -> Provider:
        return self._providers[key]

    # --- target folders (user-selected, persisted in settings) -------------
    _FOLDER_ATTR = {"upload": "upload_folder", "print": "print_folder"}

    def _apply_folder_overrides(self) -> None:
        """Override provider default folders with any the user picked earlier."""
        for key, p in self._providers.items():
            for which, attr in self._FOLDER_ATTR.items():
                stored = self.log.get_setting(f"folder:{key}:{which}")
                if stored and hasattr(p, attr):
                    setattr(p, attr, stored)

    def set_folder(self, key: str, which: str, path: str) -> None:
        """Persist and apply a chosen target folder ('upload' or 'print')."""
        attr = self._FOLDER_ATTR[which]
        self.log.set_setting(f"folder:{key}:{which}", path)
        p = self._providers[key]
        if hasattr(p, attr):
            setattr(p, attr, path)

    # --- actions -----------------------------------------------------------
    def scan_to_service(self, service_key: str, settings: ScanSettings | None = None) -> int:
        """Scan one document and upload it to the given cloud service.

        Records the activity (pending -> success/error) and returns its id.
        """
        provider = self._providers[service_key]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        ext = "pdf" if (settings or ScanSettings()).document_format.endswith("pdf") else "bin"
        filename = f"scan-{stamp}.{ext}"
        activity_id = self.log.record("scan", filename, service=service_key, status="pending")
        try:
            data = self.scanner.scan(settings)
            provider.upload(filename, data)
        except Exception as exc:  # fail loud: the row carries the reason
            self.log.update_status(activity_id, "error", str(exc))
            raise
        self.log.set_size(activity_id, len(data))
        self.log.update_status(activity_id, "success")
        return activity_id

    # --- auto-print toggle -------------------------------------------------
    def autoprint_enabled(self) -> bool:
        stored = self.log.get_setting(_AUTOPRINT_KEY)
        if stored is None:
            return self.config.autoprint.enabled
        return stored == "1"

    def set_autoprint(self, enabled: bool) -> None:
        self.log.set_setting(_AUTOPRINT_KEY, "1" if enabled else "0")

    # --- Cloud -> Print ----------------------------------------------------
    def poll_incoming_once(self) -> int:
        """Check every linked, incoming-capable service for new files and print
        them. Returns the number of documents printed this pass.

        A file is marked printed only on success, so a transient printer outage
        lets it retry next pass. Download/print errors are logged once (not every
        poll) and shown in the activity protocol.
        """
        printed = 0
        for key, provider in self._providers.items():
            if not getattr(provider, "supports_incoming", False):
                continue
            if provider.status().state is not LinkState.LINKED:
                continue
            try:
                files = provider.list_incoming()
            except Exception:
                log.warning("Could not list incoming files for %s", key, exc_info=True)
                continue
            for f in files:
                if self.log.is_printed(key, f.id):
                    continue
                if self._print_incoming(key, provider, f):
                    printed += 1
        return printed

    def _print_incoming(self, key: str, provider: Provider, f) -> bool:
        first_attempt = (key, f.id) not in self._failed_logged
        try:
            data = provider.download(f.id)
            self.printer.print_document(data, job_name=f.name)
        except Exception as exc:
            if first_attempt:
                # One visible error row the first time this file fails.
                self.log.record("print", f.name, service=key, status="error",
                                detail=str(exc))
                self._failed_logged.add((key, f.id))
            else:
                log.warning("retry print failed for %s/%s: %s", key, f.id, exc)
            return False
        self.log.record("print", f.name, service=key, status="success",
                        size_bytes=len(data))
        self.log.mark_printed(key, f.id)
        self._failed_logged.discard((key, f.id))
        return True

    def print_document(self, filename: str, data: bytes,
                       document_format: str = "application/octet-stream") -> int:
        activity_id = self.log.record("print", filename, status="pending",
                                      size_bytes=len(data))
        try:
            self.printer.print_document(data, job_name=filename,
                                        document_format=document_format)
        except Exception as exc:
            self.log.update_status(activity_id, "error", str(exc))
            raise
        self.log.update_status(activity_id, "success")
        return activity_id
