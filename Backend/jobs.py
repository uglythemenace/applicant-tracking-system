import logging
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

from auth import optional_admin, require_admin
from database import supabase
from schemas import JobArchiveUpdate, JobCreate, JobResponse, JobStatusUpdate

router = APIRouter(prefix="/jobs", tags=["Jobs"])
logger = logging.getLogger(__name__)


@router.get("/")
def get_jobs(status: Optional[str] = None, admin: dict | None = Depends(optional_admin)):
    """Public visitors see open jobs only; an authenticated admin can see all."""
    is_admin = admin is not None
    if not is_admin and status not in (None, "approved"):
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        query = supabase.table("jobs").select("*").order("created_at", desc=True)
        if is_admin:
            if status:
                query = query.eq("status", status)
        else:
            # Enforce this on the server, even if the visitor omits ?status=approved.
            query = query.eq("status", "approved").eq("is_archived", False)
        response = query.execute()
        jobs = response.data
        if not is_admin:
            jobs = [job for job in jobs if not job.get("closes_at") or job["closes_at"] >= date.today().isoformat()]
        return {"jobs": jobs}
    except Exception:
        logger.exception("Could not load jobs")
        raise HTTPException(status_code=500, detail="Could not load jobs") from None


@router.post("/", response_model=JobResponse)
def create_job(job: JobCreate, admin: dict = Depends(require_admin)):
    """Jobs posted by an admin go live right away (status 'approved')."""
    try:
        job_data = job.model_dump()
        job_data["status"] = "approved"
        job_data["is_archived"] = False
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
def get_job(job_id: int, admin: dict | None = Depends(optional_admin)):
    """Do not reveal closed jobs through their individual URLs either."""
    is_admin = admin is not None
    try:
        query = supabase.table("jobs").select("*").eq("id", job_id)
        if not is_admin:
            query = query.eq("status", "approved").eq("is_archived", False)
        response = query.execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")
        if not is_admin and response.data[0].get("closes_at") and response.data[0]["closes_at"] < date.today().isoformat():
            raise HTTPException(status_code=404, detail="Job not found")
        return response.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Could not load job")
        raise HTTPException(status_code=500, detail="Could not load job") from None


@router.patch("/{job_id}/status", response_model=JobResponse)
def update_job_status(job_id: int, update: JobStatusUpdate, admin: dict = Depends(require_admin)):
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


@router.patch(
    "/{job_id}/archive",
    response_model=JobResponse,
)
def update_job_archive(job_id: int, update: JobArchiveUpdate, admin: dict = Depends(require_admin)):
    """Archive closed jobs without deleting their application history."""
    try:
        query = supabase.table("jobs").select("id, status").eq("id", job_id).limit(1)
        response = query.execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Job not found")
        if update.is_archived and response.data[0].get("status") == "approved":
            raise HTTPException(status_code=409, detail="Close this job before archiving it")

        update_query = supabase.table("jobs").update({"is_archived": update.is_archived}).eq("id", job_id)
        if update.is_archived:
            update_query = update_query.eq("status", "rejected")
        updated = update_query.execute()
        if not updated.data:
            raise HTTPException(status_code=409, detail="Close this job before archiving it")
        return updated.data[0]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Could not archive job")
        raise HTTPException(status_code=500, detail="Could not update job") from None
