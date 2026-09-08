from fastapi import APIRouter
from .repository import supabase


router = APIRouter()


@router.get("/dashboard")
def attendance_dashboard():

    response = (
        supabase
        .table("employee_attendance")
        .select("*")
        .execute()
    )

    records = response.data or []


    result = {
        "total": len(records),
        "present": 0,
        "absent": 0,
        "late": 0,
        "half_day": 0,
        "leave": 0,
        "holiday": 0
    }


    for row in records:

        status = str(
            row.get("Status", "")
        ).lower()


        if status == "present":
            result["present"] += 1

        elif status == "absent":
            result["absent"] += 1

        elif status == "late":
            result["late"] += 1

        elif status in ["half day","half_day"]:
            result["half_day"] += 1

        elif status == "leave":
            result["leave"] += 1

        elif status in ["holiday","off"]:
            result["holiday"] += 1


    return result
