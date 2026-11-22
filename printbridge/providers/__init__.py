"""Provider registry. Importing this package registers the built-in providers."""
from __future__ import annotations

from .base import (  # noqa: F401
    LinkState,
    Provider,
    ProviderStatus,
    available_keys,
    create,
    register,
)

# Importing each module runs its @register decorator.
from . import onedrive  # noqa: F401,E402
from . import protondrive  # noqa: F401,E402
