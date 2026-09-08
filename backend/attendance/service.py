from .repository import (
    get_daily_attendance,
    get_employee_attendance
)


def daily_attendance():

    return get_daily_attendance()



def employee_history(employee_id):

    return get_employee_attendance(employee_id)
