import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from database import supabase
from auth import require_admin
from schemas import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
    TrackResponse,
)

router = APIRouter(prefix="/applications", tags=["Applications"])

# No 0/O or 1/I/L so codes are easy to read out and type from an email.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_tracking_code() -> str:
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"L2E-{body}"


# --- Public: applicant submits an application ---
@router.post("/", response_model=ApplicationResponse)
def create_application(application: ApplicationCreate):
    try:
        app_data = application.model_dump()
        app_data["email"] = app_data["email"].strip().lower()

        response = None
        # The tracking_code column is UNIQUE, so retry on the (very rare) clash.
        for _ in range(5):
            app_data["tracking_code"] = generate_tracking_code()
            try:
                response = supabase.table("applications").insert(app_data).execute()
                break
            except Exception as e:
                if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                    continue
                raise

        if response is None or not response.data:
            raise HTTPException(status_code=400, detail="Failed to submit application")
        return response.data[0]
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


# --- Public: applicant checks their own status ---
# Declared before the "/{application_id}" route so "track" is never read as an id.
@router.get("/track", response_model=TrackResponse)
def track_application(
    email: str = Query(..., min_length=3),
    code: str = Query(..., min_length=4),
):
    # Same message for "no such code" and "wrong email" so nobody can use this
    # endpoint to find out which codes or emails exist.
    not_found = HTTPException(
        status_code=404,
        detail="No application found. Check your email and tracking code.",
    )
    try:
        # Look up by code only, then compare the email in Python. This avoids
        # wildcard characters (_ and %) in emails being treated as patterns.
        result = (
            supabase.table("applications")
            .select("status, created_at, job_id, email")
            .eq("tracking_code", code.strip().upper())
            .limit(1)
            .execute()
        )
        if not result.data:
            raise not_found

        record = result.data[0]
        if (record.get("email") or "").strip().lower() != email.strip().lower():
            raise not_found

        job_title = "the position you applied for"
        job = (
            supabase.table("jobs")
            .select("title")
            .eq("id", record["job_id"])
            .limit(1)
            .execute()
        )
        if job.data:
            job_title = job.data[0]["title"]

        return {
            "job_title": job_title,
            "status": record["status"],
            "applied_at": record["created_at"],
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


# --- Admin only: list all applications ---
@router.get("/", response_model=list[ApplicationResponse], dependencies=[Depends(require_admin)])
def get_applications(job_id: int | None = None):
    try:
        query = supabase.table("applications").select("*")
        if job_id:
            query = query.eq("job_id", job_id)
        response = query.execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Admin only: change an application's status ---
@router.patch("/{application_id}", response_model=ApplicationResponse, dependencies=[Depends(require_admin)])
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
