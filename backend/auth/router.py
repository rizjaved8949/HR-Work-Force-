"""FastAPI authentication routes."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from .exceptions import AuthFlowError
from .models import (
    EmailRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MessageResponse,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
)
from .service import SupabaseAuthService


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

security = HTTPBearer(
    auto_error=False
)


def _service() -> SupabaseAuthService:
    return SupabaseAuthService()


def _raise_http_error(
    exc: AuthFlowError,
) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.to_detail(),
    ) from exc


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    payload: SignupRequest,
    service: SupabaseAuthService = Depends(
        _service
    ),
):
    try:
        return service.sign_up(
            full_name=payload.full_name,
            email=payload.email,
            password=payload.password,
            confirm_password=(
                payload.confirm_password
            ),
        )
    except AuthFlowError as exc:
        _raise_http_error(exc)


@router.post(
    "/login",
    response_model=LoginResponse,
)
def login(
    payload: LoginRequest,
    service: SupabaseAuthService = Depends(
        _service
    ),
):
    try:
        return service.sign_in(
            email=payload.email,
            password=payload.password,
        )
    except AuthFlowError as exc:
        _raise_http_error(exc)


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
)
def resend_verification(
    payload: EmailRequest,
    service: SupabaseAuthService = Depends(
        _service
    ),
):
    try:
        return service.resend_verification(
            email=payload.email,
        )
    except AuthFlowError as exc:
        _raise_http_error(exc)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
)
def forgot_password(
    payload: EmailRequest,
    service: SupabaseAuthService = Depends(
        _service
    ),
):
    try:
        return service.forgot_password(
            email=payload.email,
        )
    except AuthFlowError as exc:
        _raise_http_error(exc)


@router.post(
    "/reset-password",
    response_model=MessageResponse,
)
def reset_password(
    payload: ResetPasswordRequest,

    credentials: (
        HTTPAuthorizationCredentials | None
    ) = Depends(security),

    service: SupabaseAuthService = Depends(
        _service
    ),
):
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_RESET_SESSION",
                "message": (
                    "Password reset session is required."
                ),
            },
        )

    try:
        return service.reset_password(
            access_token=(
                credentials.credentials
            ),
            refresh_token=(
                payload.refresh_token
            ),
            new_password=(
                payload.new_password
            ),
            confirm_password=(
                payload.confirm_password
            ),
        )
    except AuthFlowError as exc:
        _raise_http_error(exc)


@router.get(
    "/me",
    response_model=MeResponse,
)
def me(
    credentials: (
        HTTPAuthorizationCredentials | None
    ) = Depends(security),

    service: SupabaseAuthService = Depends(
        _service
    ),
):
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTHENTICATION_REQUIRED",
                "message": "Authentication is required.",
            },
        )

    try:
        user = service.verify_access_token(
            credentials.credentials
        )

        return MeResponse(
            authenticated=True,
            user=user,
        )

    except AuthFlowError as exc:
        _raise_http_error(exc)


auth_router = router