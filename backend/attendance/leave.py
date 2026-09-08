from fastapi import APIRouter
from .repository import supabase


router = APIRouter()


@router.get("/leaves")
def get_leaves():

    return (
        supabase
        .table("employee_attendance")
        .select("*")
        .execute()
        .data
    )



@router.post("/leave")
def apply_leave(data:dict):

    return (
        supabase
        .table("employee_attendance")
        .insert(data)
        .execute()
        .data
    )
