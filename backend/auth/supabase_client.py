"""Supabase client factory."""

from supabase import Client, create_client

from .config import auth_settings


def get_supabase_client() -> Client:
    """Create an independent Supabase client for one operation."""

    if not auth_settings.enabled:
        raise RuntimeError(
            "Authentication is disabled. "
            "Set AUTH_ENABLED=true to use Supabase."
        )

    return create_client(
        auth_settings.supabase_url,
        auth_settings.supabase_key,
    )