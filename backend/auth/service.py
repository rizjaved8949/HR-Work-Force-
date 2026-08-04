"""Supabase access-token verification service."""

from .exceptions import AuthenticationError
from .models import AuthenticatedUser
from .supabase_client import get_supabase_client


class SupabaseAuthService:
    """Verify Supabase user access tokens."""

    def verify_access_token(
        self,
        access_token: str,
    ) -> AuthenticatedUser:
        """Return the verified Supabase user for one access token."""

        token = access_token.strip()

        if not token:
            raise AuthenticationError(
                "Access token is missing."
            )

        try:
            client = get_supabase_client()

            response = client.auth.get_user(token)
            user = response.user

            if user is None:
                raise AuthenticationError(
                    "Invalid or expired access token."
                )

            app_metadata = (
                getattr(user, "app_metadata", None)
                or {}
            )

            return AuthenticatedUser(
                id=str(user.id),
                email=user.email,
                role=app_metadata.get("role"),
            )

        except AuthenticationError:
            raise

        except Exception as exc:
            raise AuthenticationError(
                "Invalid or expired access token."
            ) from exc