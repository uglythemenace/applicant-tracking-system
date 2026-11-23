"""Interview self-scheduling tests with an in-memory database. No real service is contacted."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Backend"))


class FakeDB:
    def __init__(self):
        self.data = {"jobs": [{"id": 1}, {"id": 2}], "applications": [], "interview_slots": [], "application_audit_log": []}

    def table(self, name):
        return Q(self, name)


class Q:
    def __init__(self, db, name):
        self.db, self.name, self.f, self.op, self.payload, self.max, self.order_by = db, name, [], "select", None, None, None

    def select(self, _fields): return self
    def eq(self, k, v): self.f.append(lambda r: r.get(k) == v); return self
    def neq(self, k, v): self.f.append(lambda r: r.get(k) != v); return self
    def gt(self, k, v): self.f.append(lambda r: r.get(k) > v); return self
    def is_(self, k, v): self.f.append(lambda r: r.get(k) is None); return self
    def order(self, k, desc=False): self.order_by = k; return self
    def limit(self, n): self.max = n; return self
    def insert(self, p): self.op, self.payload = "insert", dict(p); return self
    def update(self, p): self.op, self.payload = "update", dict(p); return self
    def delete(self): self.op = "delete"; return self

    def execute(self):
        rows = self.db.data[self.name]
        if self.op == "insert":
            rec = dict(self.payload)
            rec.setdefault("id", len(rows) + 1)
            rec.setdefault("application_id", None)
            rows.append(rec)
            return SimpleNamespace(data=[dict(rec)])
        hit = [r for r in rows if all(f(r) for f in self.f)]
        if self.op == "update":
            for r in hit: r.update(self.payload)
        if self.op == "delete":
            for r in hit: rows.remove(r)
        if self.order_by: hit = sorted(hit, key=lambda r: r[self.order_by])
        if self.max is not None: hit = hit[: self.max]
        return SimpleNamespace(data=[dict(r) for r in hit])


db = FakeDB()
database_module = ModuleType("database")
database_module.supabase = db
sys.modules["database"] = database_module
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-only")
import scheduling  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from schemas import TrackRequest  # noqa: E402

ADMIN = {"email": "staff@example.com"}
RESPONSE = SimpleNamespace(headers={})


def when(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture(autouse=True)
def fresh():
    db.data = {"jobs": [{"id": 1}, {"id": 2}], "interview_slots": [], "application_audit_log": [],
               "applications": [
                   {"id": 1, "job_id": 1, "status": "interview", "email": "ada@example.com", "candidate_name": "Ada", "tracking_code": "L2E-AAAA1111"},
                   {"id": 2, "job_id": 1, "status": "interview", "email": "ben@example.com", "candidate_name": "Ben", "tracking_code": "L2E-BBBB2222"},
                   {"id": 3, "job_id": 1, "status": "pending", "email": "cy@example.com", "candidate_name": "Cy", "tracking_code": "L2E-CCCC3333"}]}


def creds(email="ada@example.com", code="L2E-AAAA1111"):
    return TrackRequest(email=email, code=code)


def book(slot_id, **kw):
    c = creds(**kw)
    return scheduling.book_slot(scheduling.BookRequest(email=c.email, code=c.code, slot_id=slot_id), RESPONSE)


def add(days=2, job=1, **kw):
    return scheduling.create_slot(scheduling.SlotCreate(job_id=job, starts_at=when(days), **kw), ADMIN)


def test_staff_cannot_offer_past_times_unknown_zones_or_missing_jobs():
    for bad in (dict(starts_at=when(-1)), dict(starts_at="not a date"), dict(starts_at=when(1), timezone="Not/AZone"), dict(starts_at=when(1), job_id=99)):
        body = {"job_id": 1, **bad}
        with pytest.raises(HTTPException) as err:
            scheduling.create_slot(scheduling.SlotCreate(**body), ADMIN)
        assert err.value.status_code in (404, 422)


def test_candidate_sees_only_free_future_times_for_their_job():
    a, b = add(1), add(3)
    add(2, job=2)
    db.data["interview_slots"].append({"id": 50, "job_id": 1, "starts_at": when(-2), "application_id": None})
    book(a["id"], email="ben@example.com", code="L2E-BBBB2222")
    out = scheduling.available_slots(creds(), RESPONSE)
    assert out["can_pick"] and [s["id"] for s in out["slots"]] == [b["id"]]
    assert "application_id" not in out["slots"][0]


def test_picking_sets_interview_and_second_person_cannot_take_it():
    s = add(2, timezone="Europe/London", location="Room 4")
    got = book(s["id"])
    assert got["interview_location"] == "Room 4"
    assert db.data["applications"][0]["interview_timezone"] == "Europe/London"
    with pytest.raises(HTTPException) as err:
        book(s["id"], email="ben@example.com", code="L2E-BBBB2222")
    assert err.value.status_code == 409
    assert db.data["interview_slots"][0]["application_id"] == 1


def test_changing_time_frees_the_old_one():
    a, b = add(1), add(2)
    book(a["id"]); book(b["id"])
    owners = {s["id"]: s["application_id"] for s in db.data["interview_slots"]}
    assert owners == {a["id"]: None, b["id"]: 1}
    assert db.data["applications"][0]["interview_at"] == b["starts_at"]


def test_wrong_code_or_wrong_stage_cannot_pick():
    s = add(2)
    with pytest.raises(HTTPException) as err:
        book(s["id"], email="ada@example.com", code="L2E-ZZZZ0000")
    assert err.value.status_code == 404
    with pytest.raises(HTTPException) as err:
        book(s["id"], email="cy@example.com", code="L2E-CCCC3333")
    assert err.value.status_code == 409
    assert scheduling.available_slots(creds("cy@example.com", "L2E-CCCC3333"), RESPONSE)["can_pick"] is False


def test_cannot_book_another_jobs_time():
    other = add(2, job=2)
    with pytest.raises(HTTPException) as err:
        book(other["id"])
    assert err.value.status_code == 404


def test_deleting_a_booked_time_clears_the_candidates_interview():
    s = add(2, location="Room 4")
    book(s["id"])
    scheduling.delete_slot(s["id"], ADMIN)
    assert db.data["interview_slots"] == []
    assert db.data["applications"][0]["interview_at"] is None
