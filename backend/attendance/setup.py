from fastapi import APIRouter
from .repository import supabase


router = APIRouter()


# ==============================
# Shifts
# ==============================

@router.get("/setup/shifts")
def get_shifts():

    return (
        supabase
        .table("attendance_shifts")
        .select("*")
        .execute()
        .data
    )


@router.post("/setup/shifts")
def create_shift(data: dict):

    return (
        supabase
        .table("attendance_shifts")
        .insert(data)
        .execute()
        .data
    )


# ==============================
# Holidays
# ==============================

@router.get("/setup/holidays")
def get_holidays():

    return (
        supabase
        .table("attendance_holidays")
        .select("*")
        .execute()
        .data
    )


@router.post("/setup/holidays")
def create_holiday(data: dict):

    return (
        supabase
        .table("attendance_holidays")
        .insert(data)
        .execute()
        .data
    )


# ==============================
# Leave Types
# ==============================

@router.get("/setup/leave-types")
def get_leave_types():

    return (
        supabase
        .table("attendance_leave_types")
        .select("*")
        .execute()
        .data
    )


@router.post("/setup/leave-types")
def create_leave_type(data: dict):

    return (
        supabase
        .table("attendance_leave_types")
        .insert(data)
        .execute()
        .data
    )


# ==============================
# Weekly Off Rules
# ==============================

@router.get("/setup/weekly-offs")
def get_weekly_offs():

    return (
        supabase
        .table("attendance_weekly_offs")
        .select("*")
        .execute()
        .data
    )


@router.post("/setup/weekly-offs")
def create_weekly_off(data: dict):

    return (
        supabase
        .table("attendance_weekly_offs")
        .insert(data)
        .execute()
        .data
    )
