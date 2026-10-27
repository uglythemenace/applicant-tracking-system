from pydantic import BaseModel
from typing import Optional, Literal

# --- Job Schemas ---
class JobCreate(BaseModel):
    title: str
    description: str
    department: Optional[str] = "General"

class JobResponse(JobCreate):
    id: int
    created_at: str
    status: Optional[str] = None

    class Config:
        from_attributes = True

class JobStatusUpdate(BaseModel):
    status: Literal["approved", "rejected"]


# --- Candidate Application Schemas ---
class ApplicationCreate(BaseModel):
    job_id: int
    candidate_name: str
    email: str
    resume_url: Optional[str] = None

class ApplicationResponse(ApplicationCreate):
    id: int
    status: str
    created_at: str
    # Applicants use this code (plus their email) to check their status.
    tracking_code: Optional[str] = None

    class Config:
        from_attributes = True

class ApplicationUpdate(BaseModel):
    status: str


# --- Public tracking schemas ---
class TrackResponse(BaseModel):
    """Only what an applicant is allowed to see about their own application."""
    job_title: str
    status: str
    applied_at: str