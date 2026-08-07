"""Authentication-specific exceptions."""


class AuthenticationConfigurationError(
    RuntimeError
):
    """Authentication configuration error."""


class AuthFlowError(Exception):
    """Safe authentication error for API clients."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "AUTH_ERROR",
        status_code: int = 400,
        action: str | None = None,
    ):
        super().__init__(message)

        self.message = message
        self.code = code
        self.status_code = status_code
        self.action = action

    def to_detail(self) -> dict:
        detail = {
            "code": self.code,
            "message": self.message,
        }

        if self.action:
            detail["action"] = self.action

        return detail


class AuthenticationError(AuthFlowError):
    def __init__(
        self,
        message: str = "Authentication is required.",
        *,
        code: str = "AUTHENTICATION_REQUIRED",
        status_code: int = 401,
        action: str | None = "LOGIN",
    ):
        super().__init__(
            message,
            code=code,
            status_code=status_code,
            action=action,
        )


class SignupError(AuthFlowError):
    """Signup error."""


class LoginError(AuthFlowError):
    """Login error."""