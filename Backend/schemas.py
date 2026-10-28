from typing import Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# --- Job schemas ---
class JobCreate(BaseModel):
    title: str
    description: str
    department: Optional[str] = "General"


class JobResponse(JobCreate):
    id: int
    created_at: str
    status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class JobStatusUpdate(BaseModel):
    status: Literal["approved", "rejected"]


# --- Candidate application schemas ---
class ApplicationCreate(BaseModel):
    job_id: int
    candidate_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
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


# Keep the response schema separate from the stricter creation schema, so an
# older record with legacy data cannot prevent the admin page from loading.
class ApplicationResponse(BaseModel):
    job_id: int
    candidate_name: str
    email: str
    resume_url: Optional[str] = None
    id: int
    status: str
    created_at: str
    tracking_code: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ApplicationUpdate(BaseModel):
    status: str


# --- Public tracking schemas ---
class TrackRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=64)

    @field_validator("email", "code", mode="before")
    @classmethod
    def strip_value(cls, value):
        return value.strip() if isinstance(value, str) else value


class TrackResponse(BaseModel):
    """Only what an applicant is allowed to see about their application."""
    job_title: str
    status: str
    applied_at: str
