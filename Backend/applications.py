import secrets
import re
import hashlib
import hmac
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from database import supabase
from auth import require_admin
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

# No 0/O or 1/I/L so codes are easy to read out and type from an email.
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
        pass
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

    remaining = _rpc_seconds(
        "check_application_duplicate_cooldown",
        {"p_key_hashes": keys},
    )
    if remaining:
        raise HTTPException(
            status_code=429,
            detail="Too many repeat attempts with details already used. Please wait before trying again.",
            headers={"Retry-After": str(remaining)},
        )

    cooldown = 0
    for key in keys:
        cooldown = max(cooldown, _rpc_seconds(
            "record_application_duplicate_attempt",
            {"p_key_hash": key},
        ))
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


# --- Public: applicant submits an application ---
@router.post("/", response_model=ApplicationResponse)
def create_application(application: ApplicationCreate):
    try:
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
        # The tracking_code column is UNIQUE, so retry on the (very rare) clash.
        for _ in range(5):
            app_data["tracking_code"] = generate_tracking_code()
            try:
                response = supabase.table("applications").insert(app_data).execute()
                break
            except Exception as e:
                error_text = str(e)
                if "APPLICATION_EMAIL_ALREADY_USED" in error_text:
                    _reject_duplicate_application(app_data["email"], phone, {"email"})
                if "APPLICATION_PHONE_ALREADY_USED" in error_text:
                    _reject_duplicate_application(app_data["email"], phone, {"phone"})
                if "duplicate" in error_text.lower() or "unique" in error_text.lower():
                    continue
                raise

        if response is None or not response.data:
            raise HTTPException(status_code=400, detail="Failed to submit application")

        saved = response.data[0]
        email_sent = send_application_received(
            saved["email"],
            saved.get("candidate_name") or "",
            get_job_title(saved.get("job_id")),
            saved["tracking_code"],
        )
        saved["tracking_email_sent"] = email_sent
        sms_queued = None
        if saved.get("sms_updates_consent") and saved.get("phone_number"):
            sms_queued = send_application_received_sms(
                saved["phone_number"],
                get_job_title(saved.get("job_id")),
                saved["tracking_code"],
            )
        saved["tracking_sms_queued"] = sms_queued
        return saved
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


# --- Public: applicant checks their own status ---
# Declared before the "/{application_id}" route so "track" is never read as an id.
@router.post("/track", response_model=TrackResponse)
def track_application(credentials: TrackRequest):
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
            .eq("tracking_code", credentials.code.strip().upper())
            .limit(1)
            .execute()
        )
        if not result.data:
            raise not_found

        record = result.data[0]
        if (record.get("email") or "").strip().lower() != credentials.email.strip().lower():
            raise not_found

        return {
            "job_title": get_job_title(record["job_id"]),
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
def update_application_status(
    application_id: int,
    update_data: ApplicationUpdate,
    background_tasks: BackgroundTasks,
):
    try:
        response = (
            supabase.table("applications")
            .update({"status": update_data.status})
            .eq("id", application_id)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Application not found")

        saved = response.data[0]
        background_tasks.add_task(
            send_status_update,
            saved["email"],
            saved.get("candidate_name") or "",
            get_job_title(saved.get("job_id")),
            saved["status"],
            saved.get("tracking_code", ""),
        )
        if (
            str(saved.get("status") or "").lower() in {"accepted", "approved", "hired", "offer", "offered", "rejected", "declined", "not selected"}
            and saved.get("sms_updates_consent")
            and saved.get("phone_number")
        ):
            background_tasks.add_task(
                send_status_sms,
                saved["phone_number"],
                get_job_title(saved.get("job_id")),
                saved["status"],
            )
        return saved
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
