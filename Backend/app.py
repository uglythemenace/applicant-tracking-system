from fastapi import FastAPI
from jobs import router as jobs_router
from applications import router as applications_router

app = FastAPI(title="Applicant Tracking System API", version="0.1.0")

app.include_router(jobs_router)
app.include_router(applications_router)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Applicant Tracking System API"}