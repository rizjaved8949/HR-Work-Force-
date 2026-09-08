from fastapi import APIRouter
from .repository import supabase


router = APIRouter()


@router.get("/register")
def attendance_register(
    month:int,
    year:int
):

    response = (
        supabase
        .table("employee_attendance")
        .select("*")
        .execute()
    )

    return response.data



@router.post("/register")
def create_attendance(data:dict):

    response = (
        supabase
        .table("employee_attendance")
        .insert(data)
        .execute()
    )

    return response.data
