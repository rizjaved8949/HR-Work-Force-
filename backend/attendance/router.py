from fastapi import APIRouter

from .service import (
    daily_attendance,
    employee_history
)

from .dashboard import router as dashboard_router
from .register import router as register_router
from .leave import router as leave_router
from .punches import router as punches_router
from .month_close import router as month_close_router
from .setup import router as setup_router


router = APIRouter()


# ============================================================
# Dashboard APIs
# ============================================================

router.include_router(
    dashboard_router
)


# ============================================================
# Register APIs
# ============================================================

router.include_router(
    register_router
)


# ============================================================
# Leave APIs
# ============================================================

router.include_router(
    leave_router
)


# ============================================================
# Punches APIs
# ============================================================

router.include_router(
    punches_router
)


# ============================================================
# Month Close APIs
# ============================================================

router.include_router(
    month_close_router
)


# ============================================================
# Setup APIs
# ============================================================

router.include_router(
    setup_router
)


# ============================================================
# Existing Attendance APIs
# Keep dynamic route at the end
# ============================================================

@router.get("/daily")
def daily():

    return daily_attendance()


@router.get("/{employee_id}")
def employee(employee_id: str):

    return employee_history(employee_id)
