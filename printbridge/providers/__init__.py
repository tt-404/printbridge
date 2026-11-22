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
# OneDrive is intentionally not registered: Microsoft requires an Azure app
# registration, which is too much friction for the home users this targets.
# The implementation stays in onedrive.py for reference.
from . import webdav  # noqa: F401,E402
from . import protondrive  # noqa: F401,E402
