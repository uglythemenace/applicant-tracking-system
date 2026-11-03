import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from auth import require_admin
from database import supabase
from schemas import JobCreate, JobResponse, JobStatusUpdate

router = APIRouter(prefix="/jobs", tags=["Jobs"])
logger = logging.getLogger(__name__)


def is_authenticated_admin(x_admin_key: Optional[str]) -> bool:
    """Treat an absent key as public; reject an invalid key rather than ignoring it."""
    if x_admin_key is None:
        return False
    require_admin(x_admin_key)
    return True


@router.get("/")
def get_jobs(
    status: Optional[str] = None,
    x_admin_key: Optional[str] = Header(default=None),
):
    """Public visitors see open jobs only; an authenticated admin can see all."""
    admin = is_authenticated_admin(x_admin_key)
    if not admin and status not in (None, "approved"):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        query = supabase.table("jobs").select("*").order("id", desc=True)
        if admin:
            if status:
                query = query.eq("status", status)
        else:
            # Enforce this on the server, even if the visitor omits ?status=approved.
            query = query.eq("status", "approved")
        response = query.execute()
        return {"jobs": response.data}
    except Exception:
        logger.exception("Could not load jobs")
        raise HTTPException(status_code=500, detail="Could not load jobs") from None


@router.post("/", response_model=JobResponse, dependencies=[Depends(require_admin)])
def create_job(job: JobCreate):
    """Jobs posted by an admin go live right away (status 'approved')."""
    try:
        job_data = job.model_dump()
        job_data["status"] = "approved"
        response = supabase.table("jobs").insert(job_data).execute()
        if not response.data:
            raise HTTPException(status_code=400, detail="Failed to create job")
        return response.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Could not create job")
        raise HTTPException(status_code=500, detail="Could not create job") from None


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, x_admin_key: Optional[str] = Header(default=None)):
    """Do not reveal closed jobs through their individual URLs either."""
    admin = is_authenticated_admin(x_admin_key)
    try:
        query = supabase.table("jobs").select("*").eq("id", job_id)
        if not admin:
            query = query.eq("status", "approved")
        response = query.execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")
        return response.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Could not load job")
        raise HTTPException(status_code=500, detail="Could not load job") from None


@router.patch("/{job_id}/status", response_model=JobResponse, dependencies=[Depends(require_admin)])
def update_job_status(job_id: int, update: JobStatusUpdate):
    """Admin approves (opens) or rejects (closes) a job posting."""
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
    except Exception:
        logger.exception("Could not update job")
        raise HTTPException(status_code=500, detail="Could not update job") from None
