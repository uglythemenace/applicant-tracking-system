import hmac
import os

from fastapi import Header, HTTPException


def require_admin(x_admin_key: str = Header(default="")):
    """Blocks a route unless the request carries the correct admin key.

    Set ADMIN_API_KEY in Backend/.env (and in your Render environment
    variables). Use a long random value, not a short password.
    """
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or not hmac.compare_digest(x_admin_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Admin access required")