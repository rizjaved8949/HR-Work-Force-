"""Public interface for the isolated authentication module."""

from .middleware import install_authentication
from .router import auth_router

__all__ = [
    "auth_router",
    "install_authentication",
]