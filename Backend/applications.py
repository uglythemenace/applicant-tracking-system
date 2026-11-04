import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response

from auth import require_admin
from database import supabase
from emailer import (
    send_application_received,
    send_application_received_sms,
    send_status_sms,
    send_status_update,
)
from schemas import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
    TrackRequest,
    TrackResponse,
)

router = APIRouter(prefix="/applications", tags=["Applications"])
logger = logging.getLogger(__name__)

# Exclude lookalike characters so codes are easier to read and type.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_tracking_code() -> str:
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"L2E-{body}"


def get_job_title(job_id) -> str:
    try:
        job = supabase.table("jobs").select("title").eq("id", job_id).limit(1).execute()
        if job.data:
            return job.data[0]["title"]
    except Exception:
        logger.warning("Could not load job title for an application notification")
    return "the position you applied for"


def _cooldown_hash(kind: str, value: str) -> str:
    secret = os.environ.get("APPLICATION_COOLDOWN_SECRET") or os.environ.get("ADMIN_API_KEY", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Application protection is not configured")
    message = f"{kind}:{value}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _rpc_seconds(function_name: str, params: dict) -> int:
    response = supabase.rpc(function_name, params).execute()
    value = response.data
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, dict) and value:
        value = next(iter(value.values()))
    return max(0, int(value or 0))


def _reject_duplicate_application(email: str, phone: str | None, duplicate_fields: set[str]):
    keys = []
    if "email" in duplicate_fields:
        keys.append(_cooldown_hash("email", email))
    if "phone" in duplicate_fields and phone:
        keys.append(_cooldown_hash("phone", phone))

    remaining = _rpc_seconds("check_application_duplicate_cooldown", {"p_key_hashes": keys})
    if remaining:
        raise HTTPException(
            status_code=429,
            detail="Too many repeat attempts with details already used. Please wait before trying again.",
            headers={"Retry-After": str(remaining)},
        )

    cooldown = 0
    for key in keys:
        cooldown = max(
            cooldown,
            _rpc_seconds("record_application_duplicate_attempt", {"p_key_hash": key}),
        )
    if cooldown:
        raise HTTPException(
            status_code=429,
            detail="Too many repeat attempts with details already used. Please wait before trying again.",
            headers={"Retry-After": str(cooldown)},
        )
    raise HTTPException(
        status_code=409,
        detail="This email address or phone number has already been used for an application. Each can only be used once.",
    )


@router.post("/", response_model=ApplicationResponse)
def create_application(application: ApplicationCreate):
    """Accept applications only for jobs that are currently open."""
    try:
        job = (
            supabase.table("jobs")
            .select("id, closes_at")
            .eq("id", application.job_id)
            .eq("status", "approved")
            .limit(1)
            .execute()
        )
        if not job.data:
            raise HTTPException(status_code=404, detail="This position is no longer open")
        if job.data[0].get("closes_at") and job.data[0]["closes_at"] < date.today().isoformat():
            raise HTTPException(status_code=404, detail="This position is no longer open")

        app_data = application.model_dump()
        app_data["email"] = app_data["email"].strip().lower()
        app_data["phone_number"] = (app_data.get("phone_number") or "").strip() or None
        app_data["sms_updates_consent"] = bool(app_data.get("sms_updates_consent"))

        phone = app_data["phone_number"]
        if app_data["sms_updates_consent"] and not phone:
            raise HTTPException(status_code=422, detail="A phone number is required for text updates")
        if phone:
            if not re.fullmatch(r"\+[0-9\s().-]+", phone):
                raise HTTPException(status_code=422, detail="Enter a phone number with its country code")
            digits = re.sub(r"\D", "", phone)
            if not 8 <= len(digits) <= 15:
                raise HTTPException(status_code=422, detail="Enter a valid international phone number")
            app_data["phone_number"] = "+" + digits
            phone = app_data["phone_number"]

        duplicate_fields = set()
        email_claim = (
            supabase.table("application_identity_claims")
            .select("claim_type")
            .eq("claim_type", "email")
            .eq("normalized_value", app_data["email"])
            .limit(1)
            .execute()
        )
        if email_claim.data:
            duplicate_fields.add("email")
        if phone:
            phone_claim = (
                supabase.table("application_identity_claims")
                .select("claim_type")
                .eq("claim_type", "phone")
                .eq("normalized_value", phone)
                .limit(1)
                .execute()
            )
            if phone_claim.data:
                duplicate_fields.add("phone")
        if duplicate_fields:
            _reject_duplicate_application(app_data["email"], phone, duplicate_fields)

        response = None
        # The tracking_code column is UNIQUE, so retry only code collisions.
        for _ in range(5):
            app_data["tracking_code"] = generate_tracking_code()
            try:
                response = supabase.table("applications").insert(app_data).execute()
                break
            except Exception as exc:
                message = str(exc)
                if "APPLICATION_EMAIL_ALREADY_USED" in message:
                    _reject_duplicate_application(app_data["email"], phone, {"email"})
                if "APPLICATION_PHONE_ALREADY_USED" in message:
                    _reject_duplicate_application(app_data["email"], phone, {"phone"})
                lowered = message.lower()
                if "tracking_code" in lowered and ("duplicate" in lowered or "unique" in lowered):
                    continue
                raise

        if response is None or not response.data:
            raise HTTPException(status_code=400, detail="Failed to submit application")

        saved = response.data[0]
        try:
            supabase.table("application_status_history").insert({
                "application_id": saved["id"], "status": saved.get("status", "pending"),
            }).execute()
        except Exception:
            logger.exception("Could not create initial application status history")
        job_title = get_job_title(saved.get("job_id"))
        email_sent = send_application_received(
            saved["email"],
            saved.get("candidate_name") or "",
            job_title,
            saved["tracking_code"],
        )
        saved["tracking_email_sent"] = email_sent
        sms_queued = None
        if saved.get("sms_updates_consent") and saved.get("phone_number"):
            sms_queued = send_application_received_sms(
                saved["phone_number"], job_title, saved["tracking_code"]
            )
        saved["tracking_sms_queued"] = sms_queued
        return saved
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Application submission failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not submit application") from None


# Declared before the /{application_id} route. POST keeps email and code out of
# the URL; no-store prevents intermediaries from caching the lookup response.
@router.post("/track", response_model=TrackResponse)
def track_application(credentials: TrackRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    not_found = HTTPException(
        status_code=404,
        detail="No application found. Check your email and tracking code.",
        headers={"Cache-Control": "no-store"},
    )
    try:
        result = (
            supabase.table("applications")
            .select("id, status, created_at, job_id, email, interview_at, interview_timezone, interview_location, interview_reschedule_url")
            .eq("tracking_code", credentials.code.strip().upper())
            .limit(1)
            .execute()
        )
        if not result.data:
            raise not_found

        record = result.data[0]
        if (record.get("email") or "").strip().lower() != credentials.email.strip().lower():
            raise not_found

        job_result = supabase.table("jobs").select("title, response_expectation").eq("id", record["job_id"]).limit(1).execute()
        job_data = (job_result.data or [{}])[0]
        history_result = (
            supabase.table("application_status_history")
            .select("status, changed_at")
            .eq("application_id", record["id"])
            .order("changed_at")
            .execute()
        )
        return {
            "job_title": job_data.get("title", get_job_title(record["job_id"])),
            "status": record["status"],
            "applied_at": record["created_at"],
            "response_expectation": job_data.get("response_expectation"),
            "history": history_result.data or [{"status": record["status"], "changed_at": record["created_at"]}],
            "interview_at": record.get("interview_at"),
            "interview_timezone": record.get("interview_timezone"),
            "interview_location": record.get("interview_location"),
            "interview_reschedule_url": record.get("interview_reschedule_url"),
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


@router.get("/", response_model=list[ApplicationResponse])
def get_applications(job_id: int | None = None, admin: dict = Depends(require_admin)):
    try:
        query = supabase.table("applications").select("*")
        if job_id:
            query = query.eq("job_id", job_id)
        response = query.execute()
        return response.data
    except Exception as exc:
        logger.error("Could not load applications (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not load applications") from None


@router.get("/{application_id}/activity")
def get_application_activity(application_id: int, admin: dict = Depends(require_admin)):
    try:
        response = (
            supabase.table("application_audit_log").select("id, actor_email, action, old_status, new_status, metadata, created_at")
            .eq("application_id", application_id).order("created_at", desc=True).limit(100).execute()
        )
        return {"activity": response.data or []}
    except Exception as exc:
        logger.error("Could not load application activity (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not load application activity") from None


@router.patch("/{application_id}", response_model=ApplicationResponse)
def update_application_status(
    application_id: int,
    update_data: ApplicationUpdate,
    background_tasks: BackgroundTasks,
    admin: dict = Depends(require_admin),
):
    try:
        current_response = supabase.table("applications").select("*").eq("id", application_id).limit(1).execute()
        if not current_response.data:
            raise HTTPException(status_code=404, detail="Application not found")
        current = current_response.data[0]
        changes = update_data.model_dump(exclude_unset=True)
        if "interview_reschedule_url" in changes and changes["interview_reschedule_url"]:
            parsed = urlsplit(changes["interview_reschedule_url"])
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise HTTPException(status_code=422, detail="Enter a valid http or https rescheduling link")
        if not changes:
            return current
        new_status = changes.get("status")
        status_changed = new_status is not None and new_status != current.get("status")
        if new_status is None:
            changes.pop("status", None)
        if status_changed:
            changes["status_updated_at"] = datetime.now(timezone.utc).isoformat()
        response = supabase.table("applications").update(changes).eq("id", application_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Application not found")

        saved = response.data[0]
        if status_changed:
            supabase.table("application_status_history").insert({
                "application_id": application_id, "status": saved["status"],
            }).execute()
        try:
            supabase.table("application_audit_log").insert({
                "application_id": application_id,
                "actor_email": admin["email"],
                "action": "status_changed" if status_changed else "application_details_updated",
                "old_status": current.get("status"),
                "new_status": saved.get("status"),
                "metadata": {"notes_updated": "reviewer_notes" in changes, "interview_updated": any(k.startswith("interview_") for k in changes)},
            }).execute()
        except Exception:
            logger.exception("Could not write application audit record")
        if not status_changed:
            return saved
        job_title = get_job_title(saved.get("job_id"))
        background_tasks.add_task(
            send_status_update,
            saved["email"],
            saved.get("candidate_name") or "",
            job_title,
            saved["status"],
            saved.get("tracking_code", ""),
        )
        final_states = {
            "accepted", "approved", "hired", "offer", "offered",
            "rejected", "declined", "not selected",
        }
        if (
            str(saved.get("status") or "").lower() in final_states
            and saved.get("sms_updates_consent")
            and saved.get("phone_number")
        ):
            background_tasks.add_task(
                send_status_sms,
                saved["phone_number"],
                job_title,
                saved["status"],
            )
        return saved
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Could not update application (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not update application") from None
