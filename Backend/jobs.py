from typing import Optional
from fastapi import APIRouter, HTTPException
from database import supabase
from schemas import JobCreate, JobResponse, JobStatusUpdate

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/")
def get_jobs(status: Optional[str] = None):
    """List jobs. Use /jobs/?status=approved for the public list."""
    try:
        query = supabase.table("jobs").select("*").order("id", desc=True)
        if status:
            query = query.eq("status", status)
        response = query.execute()
        return {"jobs": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=JobResponse)
def create_job(job: JobCreate):
    """New jobs are saved as 'pending' until an admin approves them."""
    try:
        job_data = job.model_dump()
        job_data["status"] = "approved"
        response = supabase.table("jobs").insert(job_data).execute()
        if not response.data:
            raise HTTPException(status_code=400, detail="Failed to create job")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int):
    try:
        response = supabase.table("jobs").select("*").eq("id", job_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{job_id}/status", response_model=JobResponse)
def update_job_status(job_id: int, update: JobStatusUpdate):
    """Admin approves or rejects a job posting."""
    try:
        response = (
            supabase.table("jobs")
            .update({"status": update.status})
            .eq("id", job_id)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))