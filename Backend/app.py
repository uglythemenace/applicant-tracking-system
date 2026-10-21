from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from jobs import router as jobs_router
from applications import router as applications_router

app = FastAPI(title="Applicant Tracking System API", version="0.1.0")

# Add CORS middleware to allow the frontend to communicate with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows requests from local HTML files and browsers
    allow_credentials=True,
    allow_methods=["*"],  # Allows GET, POST, PATCH, etc.
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(applications_router)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Applicant Tracking System API"}