"""OAuth configuration feature module."""

from virchow.server.features.oauth_config.api import admin_router
from virchow.server.features.oauth_config.api import router

__all__ = ["admin_router", "router"]
