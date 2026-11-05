from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from jobs import router as jobs_router
from applications import router as applications_router
from auth import router as auth_router

app = FastAPI(title="TalentFlow Applicant Tracking API", version="0.1.0")

# Add CORS middleware to allow the frontend to communicate with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows requests from local HTML files and browsers
    allow_credentials=True,
    allow_methods=["*"],  # Allows GET, POST, PATCH, etc.
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

app.include_router(jobs_router)
app.include_router(applications_router)
app.include_router(auth_router)


@app.get("/site-info")
def site_info():
    import os
    return {"contact_email": os.getenv("PUBLIC_CONTACT_EMAIL", "").strip()}

@app.get("/")
def read_root():
    return {"message": "Welcome to the Applicant Tracking System API"}
