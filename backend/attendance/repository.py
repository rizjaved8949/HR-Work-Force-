import os
from dotenv import load_dotenv
from supabase import create_client


load_dotenv()


supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)


def get_daily_attendance():

    response = (
        supabase
        .table("employee_attendance")
        .select("*")
        .execute()
    )

    return response.data



def get_employee_attendance(employee_id):

    response = (
        supabase
        .table("employee_attendance")
        .select("*")
        .eq("Employee_ID", employee_id)
        .execute()
    )

    return response.data
