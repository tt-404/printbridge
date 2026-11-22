"""Cloud provider interface and registry.

A provider is one cloud destination (OneDrive, Proton Drive, ...). The web UI
only ever talks to this interface, so adding a service is: subclass Provider,
register it, done. That is the extension point the community builds on.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol


class LinkState(str, Enum):
    LINKED = "linked"          # authenticated, ready to upload
    UNLINKED = "unlinked"      # needs the user to connect it
    PENDING = "pending"        # waiting for the user to confirm a device code
    UNAVAILABLE = "unavailable"  # cannot work on this platform (e.g. no API)


@dataclass
class ProviderStatus:
    state: LinkState
    message: str = ""
    # For device-code flows: what the user must do, surfaced in the web UI.
    user_code: str | None = None
    verification_url: str | None = None


class Provider(Protocol):
    key: str          # stable identifier, e.g. "onedrive"
    label: str        # human name shown in the UI
    experimental: bool

    def status(self) -> ProviderStatus: ...

    def begin_link(self) -> ProviderStatus:
        """Start connecting the account (e.g. request a device code)."""
        ...

    def poll_link(self) -> ProviderStatus:
        """Advance a pending link; no-op if already linked."""
        ...

    def unlink(self) -> None:
        """Forget stored credentials."""
        ...

    def upload(self, filename: str, data: bytes) -> None:
        """Upload one file. Raises on failure."""
        ...


_REGISTRY: dict[str, Callable[..., Provider]] = {}


def register(key: str) -> Callable[[Callable[..., Provider]], Callable[..., Provider]]:
    def deco(factory: Callable[..., Provider]) -> Callable[..., Provider]:
        if key in _REGISTRY:
            raise ValueError(f"provider {key!r} already registered")
        _REGISTRY[key] = factory
        return factory
    return deco


def available_keys() -> list[str]:
    return sorted(_REGISTRY)


def create(key: str, **kwargs) -> Provider:
    try:
        factory = _REGISTRY[key]
    except KeyError:
        raise KeyError(f"unknown provider {key!r}; known: {available_keys()}") from None
    return factory(**kwargs)
