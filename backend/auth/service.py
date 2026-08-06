"""Supabase signup, login, and token-verification service."""

import logging
from typing import Any

from .exceptions import (
    AuthenticationError,
    LoginError,
    SignupError,
)
from .models import (
    AuthenticatedUser,
    AuthSession,
    LoginResponse,
    SignupResponse,
)
from .supabase_client import get_supabase_client


logger = logging.getLogger(__name__)


class SupabaseAuthService:
    """Handle Supabase authentication operations."""

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Normalize a submitted email address."""

        return email.strip().lower()

    @staticmethod
    def _build_user(user: Any) -> AuthenticatedUser:
        """Convert the Supabase user object into an API model."""

        app_metadata = (
            getattr(user, "app_metadata", None)
            or {}
        )

        return AuthenticatedUser(
            id=str(user.id),
            email=getattr(user, "email", None),
            role=app_metadata.get("role"),
            email_confirmed=bool(
                getattr(
                    user,
                    "email_confirmed_at",
                    None,
                )
            ),
        )

    @staticmethod
    def _build_session(session: Any) -> AuthSession:
        """Convert the Supabase session into an API model."""

        return AuthSession(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            token_type=(
                getattr(session, "token_type", None)
                or "bearer"
            ),
            expires_in=getattr(
                session,
                "expires_in",
                None,
            ),
            expires_at=getattr(
                session,
                "expires_at",
                None,
            ),
        )

    def sign_up(
        self,
        email: str,
        password: str,
    ) -> SignupResponse:
        """Create a new Supabase user account."""

        try:
            client = get_supabase_client()

            response = client.auth.sign_up({
                "email": self._normalize_email(email),
                "password": password,
            })

            if response.user is None:
                raise SignupError(
                    "Supabase did not return a user."
                )

            user = self._build_user(response.user)

            session = (
                self._build_session(response.session)
                if response.session is not None
                else None
            )

            confirmation_required = session is None

            message = (
                "Account created successfully."
                if session is not None
                else (
                    "Account created. Please confirm your "
                    "email before logging in."
                )
            )

            return SignupResponse(
                message=message,
                user=user,
                session=session,
                email_confirmation_required=(
                    confirmation_required
                ),
            )

        except SignupError:
            raise

        except Exception as exc:
            logger.exception(
                "Supabase signup failed."
            )

            raise SignupError(
                "Unable to create account. "
                "Check the email and password."
            ) from exc

    def sign_in(
        self,
        email: str,
        password: str,
    ) -> LoginResponse:
        """Log in an existing Supabase user."""

        try:
            client = get_supabase_client()

            response = (
                client.auth.sign_in_with_password({
                    "email": self._normalize_email(email),
                    "password": password,
                })
            )

            if (
                response.user is None
                or response.session is None
            ):
                raise LoginError(
                    "Invalid email or password."
                )

            return LoginResponse(
                message="Login successful.",
                user=self._build_user(response.user),
                session=self._build_session(
                    response.session
                ),
            )

        except LoginError:
            raise

        except Exception as exc:
            logger.exception(
                "Supabase login failed."
            )

            raise LoginError(
                "Invalid email or password."
            ) from exc

    def verify_access_token(
        self,
        access_token: str,
    ) -> AuthenticatedUser:
        """Verify a Bearer access token and return its user."""

        token = access_token.strip()

        if not token:
            raise AuthenticationError(
                "Access token is missing."
            )

        try:
            client = get_supabase_client()
            response = client.auth.get_user(token)

            if response.user is None:
                raise AuthenticationError(
                    "Invalid or expired access token."
                )

            return self._build_user(response.user)

        except AuthenticationError:
            raise

        except Exception as exc:
            raise AuthenticationError(
                "Invalid or expired access token."
            ) from exc