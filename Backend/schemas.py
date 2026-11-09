from typing import Literal, Optional
from datetime import date
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# --- Job schemas ---
class JobCreate(BaseModel):
    title: str = Field(min_length=2, max_length=140)
    description: str = Field(min_length=20, max_length=12000)
    department: Optional[str] = Field(default="General", max_length=100)
    location: Optional[str] = Field(default=None, max_length=160)
    work_mode: Literal["on_site", "hybrid", "remote"] = "on_site"
    employment_type: Literal["full_time", "part_time", "contract", "temporary", "internship"] = "full_time"
    salary_min: Optional[float] = Field(default=None, ge=0)
    salary_max: Optional[float] = Field(default=None, ge=0)
    salary_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    salary_period: Literal["hour", "day", "week", "month", "year"] = "year"
    closes_at: Optional[str] = None
    response_expectation: Optional[str] = Field(default=None, max_length=240)

    @field_validator("closes_at")
    @classmethod
    def validate_close_date(cls, value):
        if value in (None, ""):
            return None
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValueError("Enter a valid closing date") from None
        return value

    @field_validator("salary_max")
    @classmethod
    def salary_range_is_valid(cls, value, info):
        minimum = info.data.get("salary_min")
        if value is not None and minimum is not None and value < minimum:
            raise ValueError("Maximum salary must be at least the minimum salary")
        return value


class JobResponse(JobCreate):
    id: int
    created_at: str
    status: Optional[str] = None
    is_archived: bool = False

    model_config = ConfigDict(from_attributes=True)


class JobUpdate(JobCreate):
    title: Optional[str] = Field(default=None, min_length=2, max_length=140)
    description: Optional[str] = Field(default=None, min_length=20, max_length=12000)
    department: Optional[str] = Field(default=None, max_length=100)
    location: Optional[str] = Field(default=None, max_length=160)
    work_mode: Optional[Literal["on_site", "hybrid", "remote"]] = None
    employment_type: Optional[Literal["full_time", "part_time", "contract", "temporary", "internship"]] = None
    salary_min: Optional[float] = Field(default=None, ge=0)
    salary_max: Optional[float] = Field(default=None, ge=0)
    salary_currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    salary_period: Optional[Literal["hour", "day", "week", "month", "year"]] = None
    closes_at: Optional[str] = None
    response_expectation: Optional[str] = Field(default=None, max_length=240)


class JobStatusUpdate(BaseModel):
    status: Literal["approved", "rejected"]


class JobArchiveUpdate(BaseModel):
    is_archived: bool


# --- Candidate application schemas ---
class ApplicationCreate(BaseModel):
    job_id: int
    candidate_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone_number: Optional[str] = Field(default=None, max_length=30)
    sms_updates_consent: bool = False
    resume_url: Optional[str] = Field(default=None, max_length=2048)

    @field_validator("candidate_name", mode="before")
    @classmethod
    def strip_candidate_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("resume_url", mode="before")
    @classmethod
    def validate_resume_url(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            return None
        try:
            parsed = urlsplit(value)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                raise ValueError
        except ValueError:
            raise ValueError("Enter a valid http or https resume link") from None
        return value


# Keep response separate so legacy records don't prevent the admin page loading.
class ApplicationResponse(BaseModel):
    job_id: int
    candidate_name: str
    email: str
    phone_number: Optional[str] = None
    sms_updates_consent: bool = False
    resume_url: Optional[str] = None
    id: int
    status: str
    created_at: str
    tracking_code: Optional[str] = None
    tracking_email_sent: Optional[bool] = None
    tracking_sms_queued: Optional[bool] = None
    reviewer_notes: Optional[str] = None
    interview_at: Optional[str] = None
    interview_timezone: Optional[str] = None
    interview_location: Optional[str] = None
    interview_reschedule_url: Optional[str] = None
    status_updated_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ApplicationUpdate(BaseModel):
    status: Optional[Literal["pending", "reviewing", "interview", "accepted", "rejected"]] = None
    reviewer_notes: Optional[str] = Field(default=None, max_length=10000)
    interview_at: Optional[str] = None
    interview_timezone: Optional[str] = Field(default=None, max_length=80)
    interview_location: Optional[str] = Field(default=None, max_length=500)
    interview_reschedule_url: Optional[str] = Field(default=None, max_length=2048)


# --- Public tracking schemas ---
class TrackRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=64)

    @field_validator("email", "code", mode="before")
    @classmethod
    def strip_value(cls, value):
        return value.strip() if isinstance(value, str) else value


class TrackLinkRequest(BaseModel):
    token: UUID


class TrackResponse(BaseModel):
    """Only what an applicant is allowed to see about their own application."""
    job_title: str
    status: str
    applied_at: str
    response_expectation: Optional[str] = None
    history: list[dict] = Field(default_factory=list)
    interview_at: Optional[str] = None
    interview_timezone: Optional[str] = None
    interview_location: Optional[str] = None
    interview_reschedule_url: Optional[str] = None


class WithdrawResponse(BaseModel):
    status: Literal["withdrawn"]
    changed_at: str
