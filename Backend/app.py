import os
from fastapi import FastAPI
from dotenv import load_dotenv
from jobs import router as jobs_router

load_dotenv()

app = FastAPI(title="Applicant Tracking System API")

# Include the jobs router
app.include_router(jobs_router)

@app.get("/")
def read_root():
    return {"message": "Welcome to the ATS API!"}