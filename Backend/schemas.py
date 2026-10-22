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

    class Config:
        from_attributes = True

class ApplicationUpdate(BaseModel):
    status: str