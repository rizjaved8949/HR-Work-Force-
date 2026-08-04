"""Supabase client used for authentication."""

from functools import lru_cache

from supabase import Client, create_client

from backend.auth.config import auth_settings


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Create and cache the Supabase Python client."""
    if not auth_settings.enabled:
        raise RuntimeError(
            "Authentication is disabled. "
            "Set AUTH_ENABLED=true to use Supabase."
        )

    return create_client(
        auth_settings.supabase_url,
        auth_settings.supabase_key,
    )