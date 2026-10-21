from pydantic import BaseModel
from typing import Optional

# --- Job Schemas ---
class JobCreate(BaseModel):
    title: str
    description: str
    department: str

class JobResponse(JobCreate):
    id: int
    created_at: str

    class Config:
        from_attributes = True


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