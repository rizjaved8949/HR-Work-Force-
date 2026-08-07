"""Authentication request and response models."""

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )
    email: str = Field(
        ...,
        min_length=3,
        max_length=254,
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
    )
    confirm_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
    )


class LoginRequest(BaseModel):
    email: str
    password: str


class EmailRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    refresh_token: str = Field(
        ...,
        min_length=1,
    )
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
    )
    confirm_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
    )


class AuthenticatedUser(BaseModel):
    id: str
    full_name: str | None = None
    email: str | None = None
    role: str | None = None
    email_confirmed: bool = False


class AuthSession(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    expires_at: int | None = None


class SignupResponse(BaseModel):
    message: str
    user: AuthenticatedUser
    email_verification_required: bool = True


class LoginResponse(BaseModel):
    message: str
    user: AuthenticatedUser
    session: AuthSession


class MeResponse(BaseModel):
    authenticated: bool = True
    user: AuthenticatedUser


class MessageResponse(BaseModel):
    message: str