"""Global FastAPI middleware for Supabase authentication."""

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from .config import auth_settings
from .exceptions import AuthenticationError
from .service import SupabaseAuthService


class SupabaseAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate every protected HTTP request."""

    def __init__(
        self,
        app: ASGIApp,
        auth_service: SupabaseAuthService | None = None,
    ) -> None:
        super().__init__(app)

        self.auth_service = (
            auth_service
            or SupabaseAuthService()
        )

    @staticmethod
    def _is_public_path(path: str) -> bool:
        """Return True when the route does not require a token."""

        normalized_path = path.rstrip("/") or "/"

        if normalized_path in auth_settings.public_paths:
            return True

        return any(
            normalized_path == prefix.rstrip("/")
            or normalized_path.startswith(
                f"{prefix.rstrip('/')}/"
            )
            for prefix in auth_settings.public_prefixes
        )

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Verify the Bearer token before calling the endpoint."""

        if not auth_settings.enabled:
            return await call_next(request)

        # Browser CORS preflight requests do not contain a user token.
        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        if self._is_public_path(request.url.path):
            return await call_next(request)

        authorization = request.headers.get(
            "Authorization",
            "",
        )

        scheme, separator, token = authorization.partition(" ")

        if (
            separator != " "
            or scheme.lower() != "bearer"
            or not token.strip()
        ):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "Authorization header must be: "
                        "Bearer <access_token>."
                    )
                },
                headers={
                    "WWW-Authenticate": "Bearer"
                },
            )

        try:
            user = await run_in_threadpool(
                self.auth_service.verify_access_token,
                token,
            )

        except AuthenticationError as exc:
            return JSONResponse(
                status_code=401,
                content={"detail": str(exc)},
                headers={
                    "WWW-Authenticate": "Bearer"
                },
            )

        # Endpoint ya router is user ko request.state.user se read kar sakta hai.
        request.state.user = user

        return await call_next(request)


def install_authentication(app: FastAPI) -> None:
    """Install the authentication middleware on the FastAPI app."""

    app.add_middleware(
        SupabaseAuthMiddleware
    )