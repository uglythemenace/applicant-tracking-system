from fastapi import APIRouter, HTTPException
from database import supabase
from schemas import ApplicationCreate, ApplicationResponse, ApplicationUpdate

router = APIRouter(prefix="/applications", tags=["Applications"])

@router.post("/", response_model=ApplicationResponse)
def create_application(application: ApplicationCreate):
    try:
        app_data = application.model_dump()
        response = supabase.table("applications").insert(app_data).execute()
        if not response.data:
            raise HTTPException(status_code=400, detail="Failed to submit application")
        return response.data[0]
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=list[ApplicationResponse])
def get_applications(job_id: int | None = None):
    try:
        query = supabase.table("applications").select("*")
        if job_id:
            query = query.eq("job_id", job_id)
        
        response = query.execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/{application_id}", response_model=ApplicationResponse)
def update_application_status(application_id: int, update_data: ApplicationUpdate):
    try:
        response = supabase.table("applications").update({"status": update_data.status}).eq("id", application_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Application not found")
        return response.data[0]
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))