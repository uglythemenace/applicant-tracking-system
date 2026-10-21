from pydantic import BaseModel
from typing import Optional

class JobCreate(BaseModel):
    title: str
    description: str
    department: str

class JobResponse(JobCreate):
    id: int
    created_at: str

    class Config:
        from_attributes = True