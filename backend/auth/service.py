"""Complete Supabase authentication service."""

import logging
from typing import Any

from email_validator import (
    EmailNotValidError,
    validate_email,
)

from .config import auth_settings
from .exceptions import (
    AuthFlowError,
    AuthenticationError,
    LoginError,
    SignupError,
)
from .models import (
    AuthenticatedUser,
    AuthSession,
    LoginResponse,
    MessageResponse,
    SignupResponse,
)
from .supabase_client import (
    get_supabase_admin_client,
    get_supabase_client,
)


logger = logging.getLogger(__name__)


def _normalize_email(email: str) -> str:
    email = (email or "").strip()

    if not email:
        raise AuthFlowError(
            "Please enter your email address.",
            code="EMAIL_REQUIRED",
            status_code=400,
        )

    try:
        result = validate_email(
            email,
            check_deliverability=False,
        )
    except EmailNotValidError as exc:
        raise AuthFlowError(
            "Please enter a valid email address.",
            code="INVALID_EMAIL",
            status_code=400,
        ) from exc

    return result.normalized.lower()


def _validate_full_name(full_name: str) -> str:
    name = " ".join(
        (full_name or "").strip().split()
    )

    if len(name) < 2:
        raise AuthFlowError(
            "Please enter your full name.",
            code="INVALID_FULL_NAME",
            status_code=400,
        )

    if len(name) > 100:
        raise AuthFlowError(
            "Full name must be 100 characters or less.",
            code="INVALID_FULL_NAME",
            status_code=400,
        )

    return name


def _validate_password(password: str) -> None:
    password = password or ""

    if len(password) < 8:
        raise AuthFlowError(
            "Password must be at least 8 characters long.",
            code="WEAK_PASSWORD",
            status_code=400,
        )

    if not any(c.isupper() for c in password):
        raise AuthFlowError(
            "Password must include an uppercase letter.",
            code="WEAK_PASSWORD",
            status_code=400,
        )

    if not any(c.islower() for c in password):
        raise AuthFlowError(
            "Password must include a lowercase letter.",
            code="WEAK_PASSWORD",
            status_code=400,
        )

    if not any(c.isdigit() for c in password):
        raise AuthFlowError(
            "Password must include a number.",
            code="WEAK_PASSWORD",
            status_code=400,
        )

    if not any(
        not c.isalnum()
        for c in password
    ):
        raise AuthFlowError(
            "Password must include a special character.",
            code="WEAK_PASSWORD",
            status_code=400,
        )


def _validate_password_pair(
    password: str,
    confirm_password: str,
) -> None:
    _validate_password(password)

    if password != confirm_password:
        raise AuthFlowError(
            "Password and confirm password do not match.",
            code="PASSWORD_MISMATCH",
            status_code=400,
        )


def _is_email_confirmed(user: Any) -> bool:
    return bool(
        getattr(
            user,
            "email_confirmed_at",
            None,
        )
        or getattr(
            user,
            "confirmed_at",
            None,
        )
    )


def _to_authenticated_user(
    user: Any,
) -> AuthenticatedUser:

    metadata = (
        getattr(user, "user_metadata", None)
        or {}
    )

    app_metadata = (
        getattr(user, "app_metadata", None)
        or {}
    )

    return AuthenticatedUser(
        id=str(user.id),
        full_name=metadata.get(
            "full_name"
        ),
        email=getattr(
            user,
            "email",
            None,
        ),
        role=app_metadata.get(
            "role"
        ),
        email_confirmed=(
            _is_email_confirmed(user)
        ),
    )


def _to_session(session: Any) -> AuthSession:
    return AuthSession(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        token_type=(
            getattr(
                session,
                "token_type",
                None,
            )
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


def _error_code(exc: Exception) -> str:
    code = (
        getattr(exc, "code", None)
        or getattr(
            exc,
            "error_code",
            None,
        )
    )

    if code:
        return str(code).lower()

    message = str(exc).lower()

    if "email not confirmed" in message:
        return "email_not_confirmed"

    if "invalid login credentials" in message:
        return "invalid_credentials"

    if "user already registered" in message:
        return "user_already_exists"

    if "rate limit" in message:
        return "rate_limited"

    return ""


def _extract_users(response: Any) -> list[Any]:
    if response is None:
        return []

    if isinstance(response, list):
        return response

    if isinstance(response, dict):
        return response.get(
            "users",
            [],
        ) or []

    users = getattr(
        response,
        "users",
        None,
    )

    if users is not None:
        return list(users)

    return []


class SupabaseAuthService:

    def _find_user_by_email(
        self,
        email: str,
    ) -> Any | None:

        admin = get_supabase_admin_client()

        page = 1
        per_page = 1000

        while True:
            response = (
                admin.auth.admin.list_users(
                    page=page,
                    per_page=per_page,
                )
            )

            users = _extract_users(
                response
            )

            for user in users:
                found_email = (
                    getattr(
                        user,
                        "email",
                        "",
                    )
                    or ""
                ).lower()

                if found_email == email:
                    return user

            if len(users) < per_page:
                break

            page += 1

        return None

    def sign_up(
        self,
        *,
        full_name: str,
        email: str,
        password: str,
        confirm_password: str,
    ) -> SignupResponse:

        full_name = _validate_full_name(
            full_name
        )
        email = _normalize_email(email)

        _validate_password_pair(
            password,
            confirm_password,
        )

        try:
            existing = (
                self._find_user_by_email(
                    email
                )
            )

            if existing is not None:
                if _is_email_confirmed(
                    existing
                ):
                    raise SignupError(
                        (
                            "An account with this email "
                            "already exists. "
                            "Please log in instead."
                        ),
                        code="EMAIL_ALREADY_EXISTS",
                        status_code=409,
                        action="LOGIN",
                    )

                raise SignupError(
                    (
                        "This email is already registered "
                        "but has not been verified. "
                        "Please verify your email or "
                        "resend the verification link."
                    ),
                    code="EMAIL_NOT_VERIFIED",
                    status_code=409,
                    action="RESEND_VERIFICATION",
                )

            client = get_supabase_client()

            response = client.auth.sign_up(
                {
                    "email": email,
                    "password": password,
                    "options": {
                        "data": {
                            "full_name": full_name,
                        },
                        "email_redirect_to": (
                            auth_settings
                            .email_verify_redirect_url
                        ),
                    },
                }
            )

            if response.user is None:
                raise SignupError(
                    "Unable to create the account.",
                    code="SIGNUP_FAILED",
                    status_code=400,
                )

            return SignupResponse(
                message=(
                    "Account created successfully. "
                    "Please check your email and "
                    "verify your account before logging in."
                ),
                user=_to_authenticated_user(
                    response.user
                ),
                email_verification_required=True,
            )

        except AuthFlowError:
            raise

        except Exception as exc:
            logger.warning(
                "Supabase signup failed: %s",
                type(exc).__name__,
            )

            code = _error_code(exc)

            if code in {
                "email_exists",
                "user_already_exists",
            }:
                raise SignupError(
                    (
                        "An account with this email "
                        "already exists. "
                        "Please log in instead."
                    ),
                    code="EMAIL_ALREADY_EXISTS",
                    status_code=409,
                    action="LOGIN",
                ) from exc

            if code == "email_address_invalid":
                raise SignupError(
                    "Please enter a valid email address.",
                    code="INVALID_EMAIL",
                    status_code=400,
                ) from exc

            if code == "email_address_not_authorized":
                raise SignupError(
                    (
                        "Verification email could not be sent "
                        "to this address."
                    ),
                    code="EMAIL_DELIVERY_UNAVAILABLE",
                    status_code=400,
                ) from exc

            if code in {
                "over_email_send_rate_limit",
                "over_request_rate_limit",
                "rate_limited",
            }:
                raise SignupError(
                    (
                        "Too many attempts. "
                        "Please wait and try again."
                    ),
                    code="RATE_LIMITED",
                    status_code=429,
                ) from exc

            raise SignupError(
                (
                    "Unable to create the account. "
                    "Please try again later."
                ),
                code="SIGNUP_FAILED",
                status_code=400,
            ) from exc

    def sign_in(
        self,
        *,
        email: str,
        password: str,
    ) -> LoginResponse:

        email = _normalize_email(email)

        if not password:
            raise LoginError(
                "Please enter your password.",
                code="PASSWORD_REQUIRED",
                status_code=400,
            )

        try:
            client = get_supabase_client()

            response = (
                client.auth
                .sign_in_with_password(
                    {
                        "email": email,
                        "password": password,
                    }
                )
            )

            if (
                response.user is None
                or response.session is None
            ):
                raise LoginError(
                    "Invalid email or password.",
                    code="INVALID_CREDENTIALS",
                    status_code=401,
                )

            if not _is_email_confirmed(
                response.user
            ):
                raise LoginError(
                    (
                        "Please verify your email "
                        "before logging in."
                    ),
                    code="EMAIL_NOT_VERIFIED",
                    status_code=403,
                    action="RESEND_VERIFICATION",
                )

            return LoginResponse(
                message="Login successful.",
                user=_to_authenticated_user(
                    response.user
                ),
                session=_to_session(
                    response.session
                ),
            )

        except AuthFlowError:
            raise

        except Exception as exc:
            code = _error_code(exc)

            if code == "email_not_confirmed":
                raise LoginError(
                    (
                        "Please verify your email "
                        "before logging in."
                    ),
                    code="EMAIL_NOT_VERIFIED",
                    status_code=403,
                    action="RESEND_VERIFICATION",
                ) from exc

            if code == "invalid_credentials":
                raise LoginError(
                    "Invalid email or password.",
                    code="INVALID_CREDENTIALS",
                    status_code=401,
                ) from exc

            raise LoginError(
                "Unable to log in right now.",
                code="LOGIN_FAILED",
                status_code=400,
            ) from exc

    def resend_verification(
        self,
        *,
        email: str,
    ) -> MessageResponse:

        email = _normalize_email(email)

        try:
            user = self._find_user_by_email(
                email
            )

            if (
                user is None
                or _is_email_confirmed(user)
            ):
                return MessageResponse(
                    message=(
                        "If this email belongs to an "
                        "unverified account, a verification "
                        "email has been sent."
                    )
                )

            client = get_supabase_client()

            client.auth.resend(
                {
                    "type": "signup",
                    "email": email,
                    "options": {
                        "email_redirect_to": (
                            auth_settings
                            .email_verify_redirect_url
                        ),
                    },
                }
            )

            return MessageResponse(
                message=(
                    "A new verification email has been sent. "
                    "Please check your inbox."
                )
            )

        except AuthFlowError:
            raise

        except Exception as exc:
            code = _error_code(exc)

            if code in {
                "over_email_send_rate_limit",
                "over_request_rate_limit",
                "rate_limited",
            }:
                raise AuthFlowError(
                    (
                        "Too many requests. "
                        "Please wait and try again."
                    ),
                    code="RATE_LIMITED",
                    status_code=429,
                ) from exc

            raise AuthFlowError(
                "Unable to resend verification email.",
                code="VERIFICATION_RESEND_FAILED",
                status_code=400,
            ) from exc

    def forgot_password(
        self,
        *,
        email: str,
    ) -> MessageResponse:

        email = _normalize_email(email)

        try:
            client = get_supabase_client()

            client.auth.reset_password_for_email(
                email,
                {
                    "redirect_to": (
                        auth_settings
                        .password_reset_redirect_url
                    ),
                },
            )

            return MessageResponse(
                message=(
                    "If an account exists for this email, "
                    "a password reset link has been sent."
                )
            )

        except Exception as exc:
            code = _error_code(exc)

            if code in {
                "over_email_send_rate_limit",
                "over_request_rate_limit",
                "rate_limited",
            }:
                raise AuthFlowError(
                    (
                        "Too many password reset requests. "
                        "Please wait and try again."
                    ),
                    code="RATE_LIMITED",
                    status_code=429,
                ) from exc

            raise AuthFlowError(
                (
                    "Unable to process password reset "
                    "right now."
                ),
                code="PASSWORD_RESET_REQUEST_FAILED",
                status_code=400,
            ) from exc

    def reset_password(
        self,
        *,
        access_token: str,
        refresh_token: str,
        new_password: str,
        confirm_password: str,
    ) -> MessageResponse:

        _validate_password_pair(
            new_password,
            confirm_password,
        )

        if not access_token or not refresh_token:
            raise AuthenticationError(
                "Password reset session is invalid.",
                code="INVALID_RESET_SESSION",
                status_code=401,
            )

        try:
            client = get_supabase_client()

            client.auth.set_session(
                access_token,
                refresh_token,
            )

            client.auth.update_user(
                {
                    "password": new_password,
                }
            )

            return MessageResponse(
                message=(
                    "Password updated successfully. "
                    "Please log in with your new password."
                )
            )

        except AuthFlowError:
            raise

        except Exception as exc:
            raise AuthFlowError(
                (
                    "The password reset link is invalid "
                    "or has expired. "
                    "Please request a new one."
                ),
                code="INVALID_OR_EXPIRED_RESET_LINK",
                status_code=401,
                action="FORGOT_PASSWORD",
            ) from exc

    def verify_access_token(
        self,
        access_token: str,
    ) -> AuthenticatedUser:

        if not access_token:
            raise AuthenticationError(
                "Access token is missing."
            )

        try:
            client = get_supabase_client()

            response = client.auth.get_user(
                access_token
            )

            if response.user is None:
                raise AuthenticationError(
                    "Invalid or expired access token."
                )

            return _to_authenticated_user(
                response.user
            )

        except AuthenticationError:
            raise

        except Exception as exc:
            raise AuthenticationError(
                "Invalid or expired access token."
            ) from exc