"""Authentication-specific exceptions."""


class AuthenticationError(Exception):
    """Raised when a Supabase access token is invalid or missing."""


class AuthenticationConfigurationError(Exception):
    """Raised when authentication configuration is incomplete."""