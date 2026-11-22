"""Application core: wires the printer, scanner, providers and activity log.

The web layer calls into this and nothing else, so the business logic stays
testable without a running web server.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import providers as provider_pkg
from .config import Config
from .db import ActivityLog
from .printer import Printer
from .providers.base import Provider
from .scanner import Scanner, ScanSettings


class Core:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.log = ActivityLog(config.database_path)
        self.scanner = Scanner(config.printer.host, config.printer.escl_path)
        self.printer = Printer(config.printer.host)
        self._providers: dict[str, Provider] = {}
        self._build_providers()

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
