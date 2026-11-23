"""Interview self-scheduling: staff offer times for a job; candidates pick one."""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from auth import require_admin
from database import supabase
from schemas import TrackRequest

router = APIRouter(prefix="/interview-slots", tags=["Interview scheduling"])
logger = logging.getLogger(__name__)
NO_STORE = {"Cache-Control": "no-store"}
SLOT_FIELDS = "id, job_id, starts_at, timezone, location, application_id"


class SlotCreate(BaseModel):
    job_id: int
    starts_at: str = Field(min_length=10, max_length=40)
    timezone: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=500)


class BookRequest(TrackRequest):
    slot_id: int


def _parse_future(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Enter a valid date and time") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if moment <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Pick a time in the future")
    return moment


def _find_candidate(credentials: TrackRequest) -> dict:
    """Same proof as the tracking page: the email and the tracking code must both match."""
    not_found = HTTPException(status_code=404, detail="No application found. Check your email and tracking code.", headers=NO_STORE)
    result = (
        supabase.table("applications")
        .select("id, job_id, status, email, candidate_name")
        .eq("tracking_code", credentials.code.strip().upper())
        .limit(1)
        .execute()
    )
    if not result.data:
        raise not_found
    record = result.data[0]
    if (record.get("email") or "").strip().lower() != credentials.email.strip().lower():
        raise not_found
    return record


# ---------- Staff ----------
@router.post("/")
def create_slot(data: SlotCreate, admin: dict = Depends(require_admin)):
    moment = _parse_future(data.starts_at)
    zone = (data.timezone or "").strip() or None
    if zone:
        try:
            ZoneInfo(zone)
        except Exception:
            raise HTTPException(status_code=422, detail="Unknown time zone") from None
    job = supabase.table("jobs").select("id").eq("id", data.job_id).limit(1).execute()
    if not job.data:
        raise HTTPException(status_code=404, detail="Job not found")
    saved = supabase.table("interview_slots").insert({
        "job_id": data.job_id, "starts_at": moment.isoformat(), "timezone": zone,
        "location": (data.location or "").strip() or None,
    }).execute()
    return saved.data[0]


@router.get("/")
def list_slots(job_id: int, admin: dict = Depends(require_admin)):
    result = (
        supabase.table("interview_slots").select(SLOT_FIELDS)
        .eq("job_id", job_id).order("starts_at").limit(200).execute()
    )
    return result.data or []


@router.delete("/{slot_id}")
def delete_slot(slot_id: int, admin: dict = Depends(require_admin)):
    slot = supabase.table("interview_slots").select(SLOT_FIELDS).eq("id", slot_id).limit(1).execute()
    if not slot.data:
        raise HTTPException(status_code=404, detail="Time not found")
    booked = slot.data[0].get("application_id")
    if booked:
        # Free the candidate's interview details too, so they can pick again.
        supabase.table("applications").update(
            {"interview_at": None, "interview_timezone": None, "interview_location": None}
        ).eq("id", booked).execute()
    supabase.table("interview_slots").delete().eq("id", slot_id).execute()
    return {"deleted": slot_id}


# ---------- Candidate ----------
@router.post("/available")
def available_slots(credentials: TrackRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        record = _find_candidate(credentials)
        if record["status"] != "interview":
            return {"can_pick": False, "slots": [], "current_slot_id": None}
        now = datetime.now(timezone.utc).isoformat()
        rows = (
            supabase.table("interview_slots").select(SLOT_FIELDS)
            .eq("job_id", record["job_id"]).gt("starts_at", now).order("starts_at").limit(100).execute()
        ).data or []
        mine = next((r["id"] for r in rows if r.get("application_id") == record["id"]), None)
        free = [
            {k: r[k] for k in ("id", "starts_at", "timezone", "location")}
            for r in rows if r.get("application_id") is None
        ]
        return {"can_pick": True, "slots": free, "current_slot_id": mine}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Listing interview times failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.", headers=NO_STORE) from None


@router.post("/book")
def book_slot(request: BookRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        record = _find_candidate(request)
        if record["status"] != "interview":
            raise HTTPException(status_code=409, detail="Interview times are not open for this application.", headers=NO_STORE)
        slot = supabase.table("interview_slots").select(SLOT_FIELDS).eq("id", request.slot_id).limit(1).execute()
        if not slot.data or slot.data[0]["job_id"] != record["job_id"]:
            raise HTTPException(status_code=404, detail="That time is no longer available.", headers=NO_STORE)
        chosen = slot.data[0]
        if datetime.fromisoformat(chosen["starts_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail="That time has passed. Pick another.", headers=NO_STORE)
        # One guarded statement: it only succeeds while the time is still free.
        claimed = (
            supabase.table("interview_slots").update({"application_id": record["id"]})
            .eq("id", chosen["id"]).is_("application_id", "null").execute()
        )
        if not claimed.data:
            raise HTTPException(status_code=409, detail="Someone just took that time. Please pick another.", headers=NO_STORE)
        try:
            supabase.table("applications").update({
                "interview_at": chosen["starts_at"], "interview_timezone": chosen.get("timezone"),
                "interview_location": chosen.get("location"),
            }).eq("id", record["id"]).execute()
        except Exception:
            supabase.table("interview_slots").update({"application_id": None}).eq("id", chosen["id"]).execute()
            raise
        # Changing time: release the earlier one for someone else.
        supabase.table("interview_slots").update({"application_id": None}) \
            .eq("application_id", record["id"]).neq("id", chosen["id"]).execute()
        try:
            supabase.table("application_audit_log").insert({
                "application_id": record["id"], "actor_email": record["email"].strip().lower(),
                "action": "candidate_picked_interview_time", "old_status": record["status"],
                "new_status": record["status"], "metadata": {"source": "candidate_tracking"},
            }).execute()
        except Exception:
            logger.exception("Could not record interview pick")
        return {
            "interview_at": chosen["starts_at"], "interview_timezone": chosen.get("timezone"),
            "interview_location": chosen.get("location"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Booking interview time failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not save your choice. Please try again.", headers=NO_STORE) from None
