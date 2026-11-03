"""API regression tests with an in-memory Supabase substitute.

No production URL, key, or database is contacted by these tests.
"""
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1] / "Backend"
sys.path.insert(0, str(BACKEND))


class FakeDatabase:
    def reset(self):
        self.data = {
            "jobs": [
                {"id": 1, "title": "Open role", "description": "Open", "department": "Engineering", "status": "approved", "created_at": "2026-10-01T00:00:00Z"},
                {"id": 2, "title": "Closed role", "description": "Private draft", "department": "Product", "status": "rejected", "created_at": "2026-10-01T00:00:00Z"},
            ],
            "applications": [],
        }

    def table(self, name):
        return FakeQuery(self, name)


class FakeQuery:
    def __init__(self, database, table):
        self.database, self.table_name = database, table
        self.filters, self.projection, self.maximum = [], "*", None
        self.operation, self.payload, self.ordering = "select", None, None

    def select(self, fields):
        self.projection = fields
        return self

    def eq(self, name, value):
        self.filters.append((name, value))
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
            table.append(record)
            return SimpleNamespace(data=[dict(record)])

        matched = [row for row in table if all(row.get(key) == value for key, value in self.filters)]
        if self.operation == "update":
            for row in matched:
                row.update(self.payload)
        if self.ordering:
            name, descending = self.ordering
            matched = sorted(matched, key=lambda row: row[name], reverse=descending)
        if self.maximum is not None:
            matched = matched[:self.maximum]
        if self.projection != "*":
            fields = [item.strip() for item in self.projection.split(",")]
            matched = [{field: row[field] for field in fields} for row in matched]
        return SimpleNamespace(data=[dict(row) for row in matched])


fake_db = FakeDatabase()
fake_db.reset()
database_module = ModuleType("database")
database_module.supabase = fake_db
sys.modules["database"] = database_module
os.environ["ADMIN_API_KEY"] = "test-admin-key-only"
from app import app  # noqa: E402 -- the fake database must be installed first


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
    assert client.get("/jobs/", headers={"X-Admin-Key": "wrong"}).status_code == 401
    response = client.get("/jobs/", headers={"X-Admin-Key": "test-admin-key-only"})
    assert [job["id"] for job in response.json()["jobs"]] == [2, 1]
    closed = client.get("/jobs/2", headers={"X-Admin-Key": "test-admin-key-only"})
    assert closed.status_code == 200 and closed.json()["status"] == "rejected"


def test_applicant_list_stays_admin_only(client):
    assert client.get("/applications/").status_code == 401
    assert client.get("/applications/", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get("/applications/", headers={"X-Admin-Key": "test-admin-key-only"}).json() == []


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


def test_tracking_uses_post_and_returns_only_public_fields(client):
    application = client.post("/applications/", json=application_payload()).json()
    payload = {"email": application["email"], "code": application["tracking_code"]}
    result = client.post("/applications/track", json=payload)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json() == {"job_title": "Open role", "status": "pending", "applied_at": "2026-10-20T00:00:00Z"}
    assert client.get("/applications/track", params=payload).status_code == 405


def test_tracking_does_not_reveal_whether_email_or_code_is_wrong(client):
    application = client.post("/applications/", json=application_payload()).json()
    bad_email = client.post("/applications/track", json={"email": "wrong@example.com", "code": application["tracking_code"]})
    bad_code = client.post("/applications/track", json={"email": application["email"], "code": "L2E-XXXXXXXX"})
    assert bad_email.status_code == bad_code.status_code == 404
    assert bad_email.json() == bad_code.json()
    assert bad_email.headers["cache-control"] == "no-store"


def test_browser_cors_allows_the_new_tracking_post_and_admin_header(client):
    for route, method, headers in [
        ("/applications/track", "POST", "content-type"),
        ("/jobs/", "GET", "x-admin-key"),
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
    result = client.get("/applications/", headers={"X-Admin-Key": "test-admin-key-only"})
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
