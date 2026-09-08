from fastapi import APIRouter

from .service import (
    daily_attendance,
    employee_history
)


router = APIRouter()


@router.get("/daily")
def daily():

    return daily_attendance()



@router.get("/{employee_id}")
def employee(employee_id:str):

    return employee_history(employee_id)
