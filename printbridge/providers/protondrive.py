"""Proton Drive provider — intentionally an honest, non-functional slot.

Proton Drive has NO official public API. The only way to reach it today is
through a reverse-engineered, end-to-end-encrypted protocol (the same approach
rclone uses). That path is:

  * unofficial and undocumented,
  * liable to break whenever Proton changes its apps,
  * in a terms-of-service grey area.

Rather than ship code that pretends to work and silently fails (which would
violate this project's "fail loud" rule), this provider reports itself as
UNAVAILABLE and refuses uploads with a clear message. If and when a maintained,
reliable client is chosen, implement the four methods below against it.
"""
from __future__ import annotations

from .base import LinkState, Provider, ProviderStatus, register

_REASON = (
    "Proton Drive has no official public API. A working connector would rely on "
    "an unofficial, reverse-engineered protocol. Not implemented yet — see the "
    "Proton Drive section in the README."
)


class ProtonDriveProvider:
    key = "protondrive"
    label = "Proton Drive"
    experimental = True

    def status(self) -> ProviderStatus:
        return ProviderStatus(LinkState.UNAVAILABLE, _REASON)

    def begin_link(self) -> ProviderStatus:
        return self.status()

    def poll_link(self) -> ProviderStatus:
        return self.status()

    def unlink(self) -> None:
        return None

    def upload(self, filename: str, data: bytes) -> None:
        raise NotImplementedError(_REASON)


@register("protondrive")
def _factory(**kwargs) -> Provider:
    return ProtonDriveProvider()
