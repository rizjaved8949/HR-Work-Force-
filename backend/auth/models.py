"""Request and response models for Supabase authentication."""

from pydantic import BaseModel, Field


class AuthCredentials(BaseModel):
    """Email and password submitted by the frontend."""

    email: str = Field(
        ...,
        min_length=3,
        max_length=320,
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
    )


class AuthenticatedUser(BaseModel):
    """Verified Supabase user details."""

    id: str
    email: str | None = None
    role: str | None = None
    email_confirmed: bool = False


class AuthSession(BaseModel):
    """Supabase session returned after successful authentication."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    expires_at: int | None = None


class SignupResponse(BaseModel):
    """Response returned after account creation."""

    message: str
    user: AuthenticatedUser
    session: AuthSession | None = None
    email_confirmation_required: bool


class LoginResponse(BaseModel):
    """Response returned after successful login."""

    message: str
    user: AuthenticatedUser
    session: AuthSession


class MeResponse(BaseModel):
    """Response returned for the currently logged-in user."""

    authenticated: bool
    user: AuthenticatedUser