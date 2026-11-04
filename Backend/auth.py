import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field

router = APIRouter(prefix="/auth", tags=["Staff sign-in"])


def _allowed_admin_emails() -> set[str]:
    return {
        email.strip().lower()
        for email in os.getenv("ADMIN_EMAILS", "").split(",")
        if email.strip()
    }


def _auth_request(path: str, *, method: str = "GET", payload: dict | None = None, access_token: str = "") -> dict:
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")
    if not base_url or not anon_key:
        raise HTTPException(status_code=503, detail="Staff sign-in is not configured")

    headers = {"apikey": anon_key, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = Request(f"{base_url}/auth/v1/{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise HTTPException(status_code=401, detail="Sign-in failed. Check your staff account details.") from None
        raise HTTPException(status_code=502, detail="The sign-in service could not complete the request") from None
    except (URLError, TimeoutError):
        raise HTTPException(status_code=503, detail="The sign-in service is temporarily unavailable") from None
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=502, detail="The sign-in service returned an invalid response") from None


def _assert_admin_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    allowed = _allowed_admin_emails()
    if not allowed:
        raise HTTPException(status_code=503, detail="No staff accounts are configured")
    if normalized not in allowed:
        raise HTTPException(status_code=403, detail="This account is not approved for staff access")
    return normalized


class StaffLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class StaffRefresh(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=4096)


def _session_response(session: dict) -> dict:
    user = session.get("user") or {}
    email = _assert_admin_email(user.get("email", ""))
    return {
        "access_token": session["access_token"],
        "refresh_token": session["refresh_token"],
        "expires_in": int(session.get("expires_in") or 3600),
        "user": {"email": email},
    }


@router.post("/login")
def staff_login(credentials: StaffLogin):
    _assert_admin_email(str(credentials.email))
    session = _auth_request(
        "token?grant_type=password",
        method="POST",
        payload={"email": str(credentials.email), "password": credentials.password},
    )
    try:
        return _session_response(session)
    except KeyError:
        raise HTTPException(status_code=502, detail="The sign-in service returned an incomplete session") from None


@router.post("/refresh")
def refresh_staff_session(credentials: StaffRefresh):
    session = _auth_request(
        "token?grant_type=refresh_token",
        method="POST",
        payload={"refresh_token": credentials.refresh_token},
    )
    try:
        return _session_response(session)
    except KeyError:
        raise HTTPException(status_code=401, detail="Your staff session expired. Sign in again.") from None


def require_admin(authorization: str = Header(default="")) -> dict:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Staff sign-in required")
    user = _auth_request("user", access_token=token)
    email = _assert_admin_email(user.get("email", ""))
    return {"id": user.get("id"), "email": email}


def optional_admin(authorization: str | None = Header(default=None)) -> dict | None:
    if not authorization:
        return None
    return require_admin(authorization)
