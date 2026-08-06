"""Authentication-specific exceptions."""


class AuthenticationError(Exception):
    """Raised when an access token cannot be verified."""


class AuthenticationConfigurationError(Exception):
    """Raised when authentication configuration is invalid."""


class SignupError(Exception):
    """Raised when a Supabase account cannot be created."""


class LoginError(Exception):
    """Raised when Supabase login fails."""