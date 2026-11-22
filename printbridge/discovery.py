"""Optional mDNS/Bonjour discovery of eSCL scanners and IPP printers.

Uses `zeroconf` if it is installed. It is imported lazily so the rest of the app
works without it; the printer page simply hides discovery when it is missing.

NOTE: mDNS browsing cannot be exercised in this build environment, so this is
written against the zeroconf API but verified only on a real network.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Device:
    ip: str
    name: str
    services: set[str] = field(default_factory=set)  # {"scan", "print"}


def available() -> bool:
    try:
        import zeroconf  # noqa: F401
        return True
    except Exception:
        return False


def discover(timeout: float = 3.0) -> list[Device]:
    """Browse for _uscan._tcp (eSCL) and _ipp._tcp (IPP) devices on the LAN.

    Raises RuntimeError if zeroconf is not installed.
    """
    try:
        from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Netzwerksuche benötigt das Paket 'zeroconf'. Installiere es mit "
            "`pip install zeroconf`."
        ) from exc

    found: dict[str, Device] = {}

    def on_change(zeroconf: "Zeroconf", service_type: str, name: str, state_change) -> None:
        if state_change is not ServiceStateChange.Added:
            return
        info = zeroconf.get_service_info(service_type, name, timeout=2000)
        if not info:
            return
        addrs = [a for a in info.parsed_addresses() if ":" not in a] or info.parsed_addresses()
        if not addrs:
            return
        ip = addrs[0]
        dev = found.setdefault(ip, Device(ip=ip, name=name.split(".")[0]))
        dev.services.add("scan" if "uscan" in service_type else "print")

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, ["_uscan._tcp.local.", "_ipp._tcp.local."], handlers=[on_change])
        time.sleep(timeout)
    finally:
        zc.close()
    return sorted(found.values(), key=lambda d: d.ip)
