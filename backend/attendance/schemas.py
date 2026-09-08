from pydantic import BaseModel
from typing import Optional


class AttendanceResponse(BaseModel):

    employee_id: Optional[str] = None
    date: Optional[str] = None
    status: Optional[str] = None
