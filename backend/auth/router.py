"""Supabase authentication API endpoints."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from .exceptions import LoginError, SignupError
from .models import (
    AuthCredentials,
    AuthenticatedUser,
    LoginResponse,
    MeResponse,
    SignupResponse,
)
from .service import SupabaseAuthService


auth_router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

auth_service = SupabaseAuthService()

# This also documents Bearer authentication in Swagger.
bearer_scheme = HTTPBearer(auto_error=False)


@auth_router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    credentials: AuthCredentials,
) -> SignupResponse:
    """Create a Supabase account using email and password."""

    try:
        return auth_service.sign_up(
            email=credentials.email,
            password=credentials.password,
        )

    except SignupError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@auth_router.post(
    "/login",
    response_model=LoginResponse,
)
def login(
    credentials: AuthCredentials,
) -> LoginResponse:
    """Log in and return Supabase session tokens."""

    try:
        return auth_service.sign_in(
            email=credentials.email,
            password=credentials.password,
        )

    except LoginError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={
                "WWW-Authenticate": "Bearer",
            },
        ) from exc


@auth_router.get(
    "/me",
    response_model=MeResponse,
)
def get_current_user(
    request: Request,
    _credentials: (
        HTTPAuthorizationCredentials | None
    ) = Depends(bearer_scheme),
) -> MeResponse:
    """Return details for the verified logged-in user."""

    user: AuthenticatedUser | None = getattr(
        request.state,
        "user",
        None,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user was not found.",
        )

    return MeResponse(
        authenticated=True,
        user=user,
    )