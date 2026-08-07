"""Supabase authentication client factories."""

from supabase import Client, create_client

from .config import auth_settings
from .exceptions import (
    AuthenticationConfigurationError,
)


def get_supabase_client() -> Client:
    """Client used for normal authentication operations."""

    if not auth_settings.supabase_url:
        raise AuthenticationConfigurationError(
            "Supabase URL is not configured."
        )

    if not auth_settings.supabase_key:
        raise AuthenticationConfigurationError(
            "Supabase publishable key is not configured."
        )

    return create_client(
        auth_settings.supabase_url,
        auth_settings.supabase_key,
    )


def get_supabase_admin_client() -> Client:
    """
    Backend-only administrative Supabase client.

    Never expose its secret key to the frontend.
    """

    if not auth_settings.supabase_url:
        raise AuthenticationConfigurationError(
            "Supabase URL is not configured."
        )

    if not auth_settings.supabase_secret_key:
        raise AuthenticationConfigurationError(
            "Supabase secret key is not configured."
        )

    return create_client(
        auth_settings.supabase_url,
        auth_settings.supabase_secret_key,
    )