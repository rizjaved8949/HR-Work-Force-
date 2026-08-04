"""Small authentication endpoints for integration testing."""

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    status,
)

from .models import AuthenticatedUser


auth_router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@auth_router.get("/me")
def get_current_authenticated_user(
    request: Request,
) -> dict:
    """Return the user attached by authentication middleware."""

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

    return {
        "authenticated": True,
        "user": user.model_dump(),
    }