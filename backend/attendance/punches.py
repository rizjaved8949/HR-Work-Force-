from fastapi import APIRouter
from .repository import supabase


router = APIRouter()


@router.get("/punches")
def punches():

    return (
        supabase
        .table("employee_attendance")
        .select("*")
        .execute()
        .data
    )



@router.post("/punches")
def manual_punch(data:dict):

    return (
        supabase
        .table("employee_attendance")
        .insert(data)
        .execute()
        .data
    )
