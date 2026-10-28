import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response

from auth import require_admin
from database import supabase
from schemas import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
    TrackRequest,
    TrackResponse,
)

router = APIRouter(prefix="/applications", tags=["Applications"])
logger = logging.getLogger(__name__)

# No 0/O or 1/I/L so codes are easy to read out and type.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_tracking_code() -> str:
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"L2E-{body}"


@router.post("/", response_model=ApplicationResponse)
def create_application(application: ApplicationCreate):
    """Accept applications only for jobs that are currently open."""
    try:
        job = (
            supabase.table("jobs")
            .select("id")
            .eq("id", application.job_id)
            .eq("status", "approved")
            .limit(1)
            .execute()
        )
        if not job.data:
            raise HTTPException(status_code=404, detail="This position is no longer open")

        app_data = application.model_dump()
        app_data["email"] = app_data["email"].strip().lower()

        response = None
        # The tracking_code column is UNIQUE, so retry a collision on that column.
        for _ in range(5):
            app_data["tracking_code"] = generate_tracking_code()
            try:
                response = supabase.table("applications").insert(app_data).execute()
                break
            except Exception as exc:
                message = str(exc).lower()
                if "tracking_code" in message and ("duplicate" in message or "unique" in message):
                    continue
                raise

        if response is None or not response.data:
            raise HTTPException(status_code=400, detail="Failed to submit application")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        # Do not echo database errors or applicant details back to the browser.
        logger.error("Application submission failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not submit application") from None


# Declared before the /{application_id} route. Using POST keeps email and code
# out of the request URL and ordinary URL access logs.
@router.post("/track", response_model=TrackResponse)
def track_application(payload: TrackRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    not_found = HTTPException(
        status_code=404,
        detail="No application found. Check your email and tracking code.",
        headers={"Cache-Control": "no-store"},
    )
    try:
        result = (
            supabase.table("applications")
            .select("status, created_at, job_id, email")
            .eq("tracking_code", payload.code.strip().upper())
            .limit(1)
            .execute()
        )
        if not result.data:
            raise not_found

        record = result.data[0]
        if (record.get("email") or "").strip().lower() != payload.email.strip().lower():
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
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Application tracking failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Something went wrong. Please try again.",
            headers={"Cache-Control": "no-store"},
        ) from None


@router.get("/", response_model=list[ApplicationResponse], dependencies=[Depends(require_admin)])
def get_applications(job_id: int | None = None):
    try:
        query = supabase.table("applications").select("*")
        if job_id:
            query = query.eq("job_id", job_id)
        response = query.execute()
        return response.data
    except Exception as exc:
        logger.error("Could not load applications (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not load applications") from None


@router.patch("/{application_id}", response_model=ApplicationResponse, dependencies=[Depends(require_admin)])
def update_application_status(application_id: int, update_data: ApplicationUpdate):
    try:
        response = (
            supabase.table("applications")
            .update({"status": update_data.status})
            .eq("id", application_id)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Application not found")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Could not update application (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not update application") from None
