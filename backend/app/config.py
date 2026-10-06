"""Compatibility imports for settings moved to :mod:`app.core.config`."""

from app.core.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
