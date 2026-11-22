"""Application core: wires the printer, scanner, providers and activity log.

The web layer calls into this and nothing else, so the business logic stays
testable without a running web server.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from . import ocr
from . import providers as provider_pkg
from .config import Config
from .db import ActivityLog
from .printer import Printer
from .providers.base import LinkState, Provider
from .scanner import Scanner, ScanSettings

log = logging.getLogger("printbridge")
_AUTOPRINT_KEY = "autoprint_enabled"
_SCANINBOX_KEY = "scaninbox_enabled"


class Core:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.log = ActivityLog(config.database_path)
        host = self.log.get_setting("printer:host") or config.printer.host
        escl = self.log.get_setting("printer:escl_path") or config.printer.escl_path
        self._printer_host = host
        self._printer_escl = escl
        self.scanner = Scanner(host, escl)
        self.printer = Printer(host)
        self._providers: dict[str, Provider] = {}
        # (service, item_id) pairs we have already logged as failed, so a file
        # that keeps failing does not spam the activity log every poll.
        self._failed_logged: set[tuple[str, str]] = set()
        # scan-inbox: last seen size per filename, to detect a finished write.
        self._inbox_seen: dict[str, int] = {}
        # last failed-configure message per provider, surfaced in the UI.
        self.last_config_error: dict[str, str] = {}
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

    # --- printer settings (user-set in the UI, persisted) ------------------
    @property
    def printer_host(self) -> str:
        return self._printer_host

    @property
    def printer_escl_path(self) -> str:
        return self._printer_escl

    def set_printer(self, host: str, escl_path: str = "/eSCL") -> None:
        host = host.strip()
        escl_path = escl_path.strip() or "/eSCL"
        self.log.set_setting("printer:host", host)
        self.log.set_setting("printer:escl_path", escl_path)
        self._printer_host = host
        self._printer_escl = escl_path
        self.scanner = Scanner(host, escl_path)
        self.printer = Printer(host)

    def test_printer(self) -> dict[str, object]:
        """Probe scanner (eSCL) and printer (IPP) reachability for the UI."""
        scan_ok, scan_detail = self.scanner.reachable()
        print_ok, print_detail = self.printer.reachable()
        return {
            "scan_ok": scan_ok, "scan_detail": scan_detail,
            "print_ok": print_ok, "print_detail": print_detail,
        }

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

    # --- upload preparation (optional OCR + auto-rename) -------------------
    def _prepare_upload(self, data: bytes, filename: str) -> tuple[bytes, str]:
        cfg = self.config.ocr
        if not cfg.enabled:
            return data, filename
        namer = None
        if cfg.naming == "letter":
            namer = ocr.derive_letter_name
        elif cfg.naming == "llm":
            from . import naming
            namer = naming.make_namer(cfg.model)
        try:
            return ocr.ocr_and_rename(data, filename, language=cfg.language,
                                      binary=cfg.binary, namer=namer)
        except Exception:
            log.warning("OCR step failed for %s; uploading original", filename,
                        exc_info=True)
            return data, filename

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
            data, filename = self._prepare_upload(data, filename)
            provider.upload(filename, data)
        except Exception as exc:  # fail loud: the row carries the reason
            self.log.update_status(activity_id, "error", str(exc))
            raise
        self.log.set_filename(activity_id, filename)
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

    # --- scan inbox (walk-up scan via SMB folder) --------------------------
    def scan_inbox_enabled(self) -> bool:
        stored = self.log.get_setting(_SCANINBOX_KEY)
        if stored is None:
            return self.config.scan_inbox.enabled
        return stored == "1"

    def set_scan_inbox(self, enabled: bool) -> None:
        self.log.set_setting(_SCANINBOX_KEY, "1" if enabled else "0")

    def poll_scan_inbox(self) -> int:
        """Upload any new files dropped in the scan-inbox folder (by the printer's
        Scan-to-Network-Folder) to the configured cloud service.

        Files still being written (younger than min_age_seconds) are skipped so a
        half-transferred scan is never uploaded. On success the local file is
        removed (it is safely in the cloud and in the log); on failure it is moved
        to a `_failed` subfolder so it is neither retried forever nor lost.
        """
        cfg = self.config.scan_inbox
        inbox = Path(cfg.dir) if cfg.dir else None
        if inbox is None or not inbox.is_dir():
            return 0
        provider = self._providers.get(cfg.service)
        if provider is None or provider.status().state is not LinkState.LINKED:
            return 0
        now = time.time()
        count = 0
        current: set[str] = set()
        for f in sorted(inbox.iterdir()):
            if not f.is_file() or f.name.startswith(".") or f.name.startswith("_"):
                continue
            try:
                stat = f.stat()
            except OSError:
                continue
            current.add(f.name)
            size = stat.st_size
            # Only process once the file is finished: old enough AND the same
            # size as the previous poll. A scanner writes the PDF trailer last,
            # so grabbing it mid-write yields a truncated, unreadable file.
            if now - stat.st_mtime < cfg.min_age_seconds or self._inbox_seen.get(f.name) != size:
                self._inbox_seen[f.name] = size
                continue
            activity_id = self.log.record("scan", f.name, service=cfg.service,
                                          status="pending", size_bytes=size)
            try:
                data = f.read_bytes()
                data, upload_name = self._prepare_upload(data, f.name)
                provider.upload(upload_name, data)
            except Exception as exc:
                self.log.update_status(activity_id, "error", str(exc))
                failed = inbox / "_failed"
                failed.mkdir(exist_ok=True)
                try:
                    f.rename(failed / f.name)
                except OSError:
                    pass
                self._inbox_seen.pop(f.name, None)
                continue
            self.log.set_filename(activity_id, upload_name)
            self.log.set_size(activity_id, len(data))
            self.log.update_status(activity_id, "success")
            f.unlink(missing_ok=True)
            self._inbox_seen.pop(f.name, None)
            count += 1
        # Forget files that have disappeared so the map does not grow forever.
        for name in [n for n in self._inbox_seen if n not in current]:
            self._inbox_seen.pop(name, None)
        return count

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
