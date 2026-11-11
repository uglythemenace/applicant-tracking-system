"""Tests for the applicant status emails. No emails are sent: the sender is replaced."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Backend"))

import emailer  # noqa: E402


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(emailer, "_send", lambda to, subject, body: sent.append((subject, body)) or True)
    return sent


def test_every_known_status_gets_its_own_plain_message(monkeypatch):
    sent = _capture(monkeypatch)
    for status in ["pending", "reviewing", "interview", "accepted", "rejected", "withdrawn"]:
        emailer.send_status_update("a@example.com", "Maria", "Backend Developer", status, "L2E-ABC12345")
    subjects = [subject for subject, _ in sent]
    assert len(set(subjects)) == 6
    assert all("Backend Developer" in subject for subject in subjects)
    # Raw status words like "New status: rejected" are no longer shown.
    assert all("New status:" not in body for _, body in sent)
    assert all("L2E-ABC12345" in body for _, body in sent)


def test_rejection_is_respectful_and_points_to_other_roles(monkeypatch):
    sent = _capture(monkeypatch)
    emailer.send_status_update("a@example.com", "Maria", "Backend Developer", "rejected", "L2E-ABC12345")
    subject, body = sent[0]
    assert "rejected" not in subject.lower()
    assert "Thank you" in body and "not to move forward" in body
    assert emailer.FRONTEND_URL + "/jobs" in body


def test_unknown_status_still_reads_clearly(monkeypatch):
    sent = _capture(monkeypatch)
    emailer.send_status_update("a@example.com", "Maria", "Dev", "second_round", "L2E-X")
    assert "Second round" in sent[0][1]


def test_user_supplied_text_is_escaped_in_the_body_but_not_in_the_subject(monkeypatch):
    sent = _capture(monkeypatch)
    emailer.send_status_update("a@example.com", "<script>x</script>", "Dev & Ops", "reviewing", "L2E-X")
    subject, body = sent[0]
    assert subject.endswith("Dev & Ops")
    assert "<script>" not in body and "Dev &amp; Ops" in body


def test_interview_email_shows_local_time_place_and_safe_reschedule_link(monkeypatch):
    sent = _capture(monkeypatch)
    emailer.send_status_update(
        "a@example.com", "Maria", "Dev", "interview", "L2E-X",
        "2026-11-18T22:30:00+00:00", "America/Los_Angeles",
        "Video call: https://meet.example.com/abc", "https://calendar.example.com/r?a=1&b=2",
    )
    body = sent[0][1]
    assert "Wednesday, 18 November 2026 at 14:30 (America/Los_Angeles)" in body
    assert "Video call: https://meet.example.com/abc" in body
    assert 'href="https://calendar.example.com/r?a=1&amp;b=2"' in body


def test_interview_email_without_details_says_they_are_coming(monkeypatch):
    sent = _capture(monkeypatch)
    emailer.send_status_update("a@example.com", "Maria", "Dev", "interview", "L2E-X")
    assert "will share the interview time and place soon" in sent[0][1]


def test_bad_timezone_and_unsafe_link_are_handled(monkeypatch):
    sent = _capture(monkeypatch)
    emailer.send_status_update(
        "a@example.com", "Maria", "Dev", "interview", "L2E-X",
        "2026-11-18T22:30:00Z", "Not/AZone", None, "javascript:alert(1)",
    )
    body = sent[0][1]
    assert "22:30 (UTC)" in body
    assert "javascript:" not in body
