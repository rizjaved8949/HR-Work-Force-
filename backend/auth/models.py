"""Models used by the Supabase authentication layer."""

from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    """A user whose Supabase access token has been verified."""

    id: str
    email: str | None = None
    role: str | None = None