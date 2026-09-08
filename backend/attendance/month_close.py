from fastapi import APIRouter


router = APIRouter()


@router.get("/month-close")
def month_close():

    return {
        "processed_rows":0,
        "absent_days":0,
        "summaries":0,
        "locked_rows":0,
        "status":"Open"
    }



@router.post("/month-close/generate")
def generate_summary():

    return {
        "message":"Monthly summary generated"
    }



@router.post("/month-close/lock")
def lock_month():

    return {
        "message":"Month locked"
    }
