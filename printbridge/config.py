"""Configuration loading and the data directory.

Non-secret settings live in config.yaml. Secrets (OAuth tokens) are written by
the providers into the data directory, never into config.yaml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def data_dir() -> Path:
    """Directory for the database and secret token files.

    Honors $PRINTBRIDGE_DATA_DIR, else XDG default. Created if missing.
    """
    override = os.environ.get("PRINTBRIDGE_DATA_DIR")
    base = Path(override) if override else Path.home() / ".local" / "share" / "printbridge"
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class PrinterConfig:
    host: str = "192.168.0.98"
    escl_path: str = "/eSCL"


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class AutoprintConfig:
    # Default state when the DB has no stored toggle yet.
    enabled: bool = False
    # How often to poll watched cloud folders, in seconds.
    interval_seconds: int = 60


@dataclass
class Config:
    printer: PrinterConfig = field(default_factory=PrinterConfig)
    web: WebConfig = field(default_factory=WebConfig)
    autoprint: AutoprintConfig = field(default_factory=AutoprintConfig)
    database: str = "printbridge.db"
    services: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def database_path(self) -> Path:
        p = Path(self.database)
        return p if p.is_absolute() else data_dir() / p

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        """Load config.yaml. Missing file yields sensible defaults."""
        if path is None:
            path = os.environ.get("PRINTBRIDGE_CONFIG", "config.yaml")
        path = Path(path)
        raw: dict[str, Any] = {}
        if path.exists():
            raw = yaml.safe_load(path.read_text()) or {}
        return cls(
            printer=PrinterConfig(**(raw.get("printer") or {})),
            web=WebConfig(**(raw.get("web") or {})),
            autoprint=AutoprintConfig(**(raw.get("autoprint") or {})),
            database=raw.get("database", "printbridge.db"),
            services=raw.get("services") or {},
        )
