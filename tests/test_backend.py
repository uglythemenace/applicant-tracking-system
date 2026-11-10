"""API regression tests with an in-memory Supabase substitute.

No production URL, key, or database is contacted by these tests. Staff auth is
stubbed at the Supabase token-verification boundary; everything else runs the
real route code.
"""
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1] / "Backend"
sys.path.insert(0, str(BACKEND))

STAFF_TOKEN = "good-staff-token-only"
STAFF_HEADERS = {"Authorization": f"Bearer {STAFF_TOKEN}"}


class FakeStorage:
    def __init__(self):
        self.objects = {}

    def from_(self, _bucket):
        return self

    def upload(self, path, content, file_options=None):
        self.objects[path] = content

    def remove(self, paths):
        for path in paths:
            self.objects.pop(path, None)

    def create_signed_url(self, path, expires_in):
        return {"signedURL": f"https://files.test/{path}"}


class FakeDatabase:
    def reset(self):
        self.data = {
            "jobs": [
                {"id": 1, "title": "Open role", "description": "Open role description for the tests.", "department": "Engineering", "status": "approved", "is_archived": False, "created_at": "2026-10-01T00:00:00Z"},
                {"id": 2, "title": "Closed role", "description": "Private draft description for the tests.", "department": "Product", "status": "rejected", "is_archived": False, "created_at": "2026-10-02T00:00:00Z"},
            ],
            "applications": [],
            "application_identity_claims": [],
            "application_status_history": [],
            "application_audit_log": [],
            "application_resume_deletion_queue": [],
        }
        self.storage = FakeStorage()

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, params):
        # Cooldown helpers report "no wait"; retention helpers report zero rows.
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[0]))


class FakeQuery:
    def __init__(self, database, table):
        self.database, self.table_name = database, table
        self.filters, self.projection, self.maximum = [], "*", None
        self.operation, self.payload, self.ordering = "select", None, None

    def select(self, fields):
        self.projection = fields
        return self

    def eq(self, name, value):
        self.filters.append(("eq", name, value))
        return self

    def neq(self, name, value):
        self.filters.append(("neq", name, value))
        return self

    def in_(self, name, values):
        self.filters.append(("in", name, list(values)))
        return self

    def order(self, name, desc=False):
        self.ordering = (name, desc)
        return self

    def limit(self, amount):
        self.maximum = amount
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", dict(payload)
        return self

    def update(self, payload):
        self.operation, self.payload = "update", dict(payload)
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def _matches(self, row):
        for op, key, value in self.filters:
            actual = row.get(key)
            if op == "eq" and actual != value:
                return False
            if op == "neq" and actual == value:
                return False
            if op == "in" and actual not in value:
                return False
        return True

    def execute(self):
        table = self.database.data[self.table_name]
        if self.operation == "insert":
            record = dict(self.payload)
            if self.table_name == "applications":
                if any(row.get("tracking_code") == record.get("tracking_code") for row in table):
                    raise Exception('duplicate key in applications_tracking_code_key')
                record.setdefault("id", len(table) + 1)
                record.setdefault("status", "pending")
                record.setdefault("created_at", "2026-10-20T00:00:00Z")
            if self.table_name == "application_status_history":
                record.setdefault("changed_at", "2026-10-20T00:00:00Z")
            if self.table_name == "application_audit_log":
                record.setdefault("id", len(table) + 1)
                record.setdefault("created_at", "2026-10-20T00:00:00Z")
            table.append(record)
            return SimpleNamespace(data=[dict(record)])

        matched = [row for row in table if self._matches(row)]
        if self.operation == "update":
            for row in matched:
                row.update(self.payload)
        elif self.operation == "delete":
            for row in matched:
                table.remove(row)
            return SimpleNamespace(data=[dict(row) for row in matched])
        if self.ordering:
            name, descending = self.ordering
            matched = sorted(matched, key=lambda row: row.get(name) or "", reverse=descending)
        if self.maximum is not None:
            matched = matched[:self.maximum]
        if self.projection != "*":
            fields = [item.strip() for item in self.projection.split(",")]
            matched = [{field: row.get(field) for field in fields} for row in matched]
        return SimpleNamespace(data=[dict(row) for row in matched])


fake_db = FakeDatabase()
fake_db.reset()
database_module = ModuleType("database")
database_module.supabase = fake_db
sys.modules["database"] = database_module
os.environ["ADMIN_API_KEY"] = "test-admin-key-only"
os.environ["ADMIN_EMAILS"] = "staff@example.com"
os.environ["SUPABASE_URL"] = "https://auth.test"
os.environ["SUPABASE_ANON_KEY"] = "anon-test-only"
from app import app  # noqa: E402 -- the fake database must be installed first
import auth as auth_module  # noqa: E402


def fake_auth_request(path, *, method="GET", payload=None, access_token=""):
    if path == "user":
        if access_token == STAFF_TOKEN:
            return {"id": "staff-1", "email": "staff@example.com"}
        raise HTTPException(status_code=401, detail="Invalid token")
    raise AssertionError(f"Unexpected auth call: {path}")


@pytest.fixture(autouse=True)
def staff_auth(monkeypatch):
    monkeypatch.setattr(auth_module, "_auth_request", fake_auth_request)


@pytest.fixture
def client():
    fake_db.reset()
    with TestClient(app) as test_client:
        yield test_client


def application_payload(**changes):
    payload = {"job_id": 1, "candidate_name": "  Ada Lovelace  ", "email": "Ada@Example.com", "resume_url": "https://example.com/cv"}
    payload.update(changes)
    return payload


def test_public_job_list_only_shows_approved(client):
    for path in ("/jobs/", "/jobs/?status=approved"):
        response = client.get(path)
        assert response.status_code == 200
        assert [job["id"] for job in response.json()["jobs"]] == [1]
    assert client.get("/jobs/?status=rejected").status_code == 403


def test_closed_job_detail_and_list_require_admin(client):
    assert client.get("/jobs/2").status_code == 404
    assert client.get("/jobs/1").status_code == 200
    assert client.get("/jobs/", headers={"Authorization": "Bearer wrong-token"}).status_code == 401
    response = client.get("/jobs/", headers=STAFF_HEADERS)
    assert [job["id"] for job in response.json()["jobs"]] == [2, 1]
    closed = client.get("/jobs/2", headers=STAFF_HEADERS)
    assert closed.status_code == 200 and closed.json()["status"] == "rejected"


def test_applicant_list_stays_admin_only(client):
    assert client.get("/applications/").status_code == 401
    assert client.get("/applications/", headers={"Authorization": "Bearer wrong-token"}).status_code == 401
    assert client.get("/applications/", headers=STAFF_HEADERS).json() == []


@pytest.mark.parametrize("changes", [
    {"candidate_name": "   "},
    {"email": "not-an-email"},
    {"resume_url": "javascript:alert(1)"},
    {"resume_url": "https:///missing-host"},
])
def test_invalid_application_never_reaches_database(client, changes):
    assert client.post("/applications/", json=application_payload(**changes)).status_code == 422
    assert fake_db.data["applications"] == []


def test_closed_and_missing_jobs_cannot_receive_applications(client):
    for job_id in (2, 999):
        response = client.post("/applications/", json=application_payload(job_id=job_id))
        assert response.status_code == 404
    assert fake_db.data["applications"] == []


def test_create_application_normalizes_data_and_returns_tracking_code(client):
    response = client.post("/applications/", json=application_payload())
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["candidate_name"] == "Ada Lovelace"
    assert record["email"] == "ada@example.com"
    assert record["resume_url"] == "https://example.com/cv"
    assert record["tracking_code"].startswith("L2E-")
    assert len(fake_db.data["applications"]) == 1
    assert fake_db.data["application_status_history"][0]["status"] == "pending"


def test_duplicate_email_is_rejected_with_cooldown_lookup(client):
    assert client.post("/applications/", json=application_payload()).status_code == 200
    fake_db.data["application_identity_claims"].append(
        {"claim_type": "email", "normalized_value": "ada@example.com"}
    )
    response = client.post("/applications/", json=application_payload())
    assert response.status_code == 409
    assert len(fake_db.data["applications"]) == 1


def test_tracking_uses_post_and_returns_only_public_fields(client):
    application = client.post("/applications/", json=application_payload()).json()
    payload = {"email": application["email"], "code": application["tracking_code"]}
    result = client.post("/applications/track", json=payload)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    body = result.json()
    assert body["job_title"] == "Open role"
    assert body["status"] == "pending"
    assert body["applied_at"] == "2026-10-20T00:00:00Z"
    assert body["history"] == [{"status": "pending", "changed_at": "2026-10-20T00:00:00Z"}]
    assert "email" not in body and "candidate_name" not in body and "resume_url" not in body
    assert client.get("/applications/track", params=payload).status_code == 405


def test_tracking_does_not_reveal_whether_email_or_code_is_wrong(client):
    application = client.post("/applications/", json=application_payload()).json()
    bad_email = client.post("/applications/track", json={"email": "wrong@example.com", "code": application["tracking_code"]})
    bad_code = client.post("/applications/track", json={"email": application["email"], "code": "L2E-XXXXXXXX"})
    assert bad_email.status_code == bad_code.status_code == 404
    assert bad_email.json() == bad_code.json()
    assert bad_email.headers["cache-control"] == "no-store"


def test_browser_cors_allows_the_new_tracking_post_and_bearer_header(client):
    for route, method, headers in [
        ("/applications/track", "POST", "content-type"),
        ("/jobs/", "GET", "authorization"),
    ]:
        response = client.options(route, headers={
            "Origin": "https://applicant-tracking-system-frontend.vercel.app",
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://applicant-tracking-system-frontend.vercel.app"


def test_legacy_records_do_not_break_the_admin_list(client):
    fake_db.data["applications"].append({
        "id": 8, "job_id": 1, "candidate_name": " ", "email": "old-invalid-email",
        "resume_url": "javascript:alert(1)", "status": "pending",
        "created_at": "2026-10-01T00:00:00Z", "tracking_code": "L2E-ABC23456",
    })
    result = client.get("/applications/", headers=STAFF_HEADERS)
    assert result.status_code == 200
    assert result.json()[0]["id"] == 8


def test_tracking_code_collision_is_retried(client, monkeypatch):
    import applications
    fake_db.data["applications"].append({"tracking_code": "L2E-ABC23456"})
    codes = iter(["L2E-ABC23456", "L2E-DEF23456"])
    monkeypatch.setattr(applications, "generate_tracking_code", lambda: next(codes))
    response = client.post("/applications/", json=application_payload())
    assert response.status_code == 200
    assert response.json()["tracking_code"] == "L2E-DEF23456"


def test_database_errors_do_not_leak_to_visitors(client, monkeypatch):
    def fail(_name):
        raise RuntimeError("SECRET_DATABASE_DETAIL")
    monkeypatch.setattr(fake_db, "table", fail)
    response = client.get("/jobs/")
    assert response.status_code == 500
    assert "SECRET_DATABASE_DETAIL" not in response.text


def test_candidate_can_withdraw_once_and_not_reopen(client):
    application = client.post("/applications/", json=application_payload()).json()
    credentials = {"email": application["email"], "code": application["tracking_code"]}
    result = client.post("/applications/withdraw", json=credentials)
    assert result.status_code == 200 and result.json()["status"] == "withdrawn"
    assert result.headers["cache-control"] == "no-store"
    again = client.post("/applications/withdraw", json=credentials)
    assert again.status_code == 200 and again.json()["status"] == "withdrawn"
    reopen = client.patch(f"/applications/{application['id']}", json={"status": "pending"}, headers=STAFF_HEADERS)
    assert reopen.status_code == 409
    assert fake_db.data["application_audit_log"][-1]["action"] == "candidate_withdrew"


def test_finalized_application_cannot_be_withdrawn(client):
    application = client.post("/applications/", json=application_payload()).json()
    client.patch(f"/applications/{application['id']}", json={"status": "accepted"}, headers=STAFF_HEADERS)
    result = client.post("/applications/withdraw", json={"email": application["email"], "code": application["tracking_code"]})
    assert result.status_code == 409


def test_staff_status_change_records_history_and_audit(client):
    application = client.post("/applications/", json=application_payload()).json()
    result = client.patch(f"/applications/{application['id']}", json={"status": "reviewing", "reviewer_notes": "Strong CV"}, headers=STAFF_HEADERS)
    assert result.status_code == 200
    assert result.json()["status"] == "reviewing"
    assert result.json()["reviewer_notes"] == "Strong CV"
    history = fake_db.data["application_status_history"]
    assert [entry["status"] for entry in history] == ["pending", "reviewing"]
    audit = fake_db.data["application_audit_log"][-1]
    assert audit["actor_email"] == "staff@example.com"
    assert audit["old_status"] == "pending" and audit["new_status"] == "reviewing"
    tracked = client.post("/applications/track", json={"email": application["email"], "code": application["tracking_code"]}).json()
    assert [entry["status"] for entry in tracked["history"]] == ["pending", "reviewing"]


def test_create_response_hides_the_bearer_token(client):
    response = client.post("/applications/", json=application_payload())
    assert response.status_code == 200
    assert "track_token" not in response.json()
    stored = fake_db.data["applications"][0]
    assert stored.get("track_token") and stored["track_token"] != stored["tracking_code"]


def test_staff_list_never_exposes_tracking_tokens(client):
    client.post("/applications/", json=application_payload())
    rows = client.get("/applications/", headers=STAFF_HEADERS).json()
    assert rows and all("track_token" not in row for row in rows)


def test_private_link_opens_the_dashboard_without_email_or_code(client):
    import uuid
    client.post("/applications/", json=application_payload())
    token = fake_db.data["applications"][0]["track_token"]
    result = client.post("/applications/track-link", json={"token": token})
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    body = result.json()
    assert body["job_title"] == "Open role" and body["status"] == "pending"
    assert "email" not in body and "candidate_name" not in body
    unknown = client.post("/applications/track-link", json={"token": str(uuid.uuid4())})
    assert unknown.status_code == 404
    assert unknown.headers["cache-control"] == "no-store"
    assert client.post("/applications/track-link", json={"token": "not-a-uuid"}).status_code == 422
    assert client.get("/applications/track-link", params={"token": token}).status_code == 405


def test_private_link_can_withdraw_but_not_reopen(client):
    client.post("/applications/", json=application_payload())
    application = fake_db.data["applications"][0]
    credentials = {"token": application["track_token"]}
    result = client.post("/applications/withdraw-link", json=credentials)
    assert result.status_code == 200 and result.json()["status"] == "withdrawn"
    assert result.headers["cache-control"] == "no-store"
    again = client.post("/applications/withdraw-link", json=credentials)
    assert again.status_code == 200 and again.json()["status"] == "withdrawn"
    reopen = client.patch(f"/applications/{application['id']}", json={"status": "pending"}, headers=STAFF_HEADERS)
    assert reopen.status_code == 409
    assert fake_db.data["application_audit_log"][-1]["action"] == "candidate_withdrew"
