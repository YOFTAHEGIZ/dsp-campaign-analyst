"""
Tests for scripts/send_weekly_progress.py. No network and no real email: GitHub's answers and
the mail server are replaced by small stand-ins.

    python -m pytest scripts/tests
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import send_weekly_progress as weekly  # noqa: E402

NOW = datetime(2026, 11, 13, 18, 0, tzinfo=weekly.TIMEZONE)
SINCE = NOW - timedelta(days=7)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ISSUES = [
    {"number": 7, "title": "Hourly pipeline", "html_url": "https://github.com/x/y/issues/7",
     "closed_at": iso(NOW - timedelta(days=1))},                                  # closed this week
    {"number": 3, "title": "Old task", "html_url": "https://github.com/x/y/issues/3",
     "closed_at": iso(NOW - timedelta(days=20))},                                 # closed long ago
    {"number": 9, "title": "Dashboard filters", "html_url": "https://github.com/x/y/pull/9",
     "closed_at": iso(NOW - timedelta(days=2)), "pull_request": {"merged_at": iso(NOW - timedelta(days=2))}},
    {"number": 10, "title": "Abandoned idea", "html_url": "https://github.com/x/y/pull/10",
     "closed_at": iso(NOW - timedelta(days=2)), "pull_request": {"merged_at": None}},
]

LOG = """# Learning Log

## 2026-11-12: Hourly pipeline

- **Learned:** a watermark makes hourly runs safe to repeat.
- **Blocked by:** late clicks.
- **Got unblocked by:** reload the impression's day.
- **Next:** daily PCA email.

## 2026-11-10 - Dashboard filters
* **Learned**: filters in the URL can be shared.
- **Blocked by:** red imports in VS Code.
- **Got unblocked by:**

## 2026-10-30: README

- **Learned:** an old lesson, not this week.

## Resources

- **Learned:** not an entry
"""


def test_closed_this_week_keeps_closed_issues_and_merged_pull_requests():
    done = weekly.closed_this_week(ISSUES, SINCE)
    assert [(d["kind"], d["number"]) for d in done] == [("Issue", 7), ("Pull request", 9)]


def test_status_blocked_label_wins():
    items = weekly.open_issues([{"number": 4, "title": "Neon down", "html_url": "u",
                                 "labels": [{"name": "Blocked"}]}])
    assert weekly.work_out_status(items, [], NOW)[0] == "Blocked"


def test_status_overdue_milestone_is_slightly_behind():
    milestones = [{"title": "Week 2", "due_on": iso(NOW - timedelta(days=1)), "open_issues": 2}]
    status, reason = weekly.work_out_status([], milestones, NOW)
    assert status == "Slightly behind" and "Week 2 (2 open)" in reason


def test_status_on_track_and_override():
    future = [{"title": "Week 3", "due_on": iso(NOW + timedelta(days=5)), "open_issues": 4}]
    assert weekly.work_out_status([], future, NOW)[0] == "On track"
    assert weekly.work_out_status([], future, NOW, "slightly behind")[0] == "Slightly behind"


def test_learning_log_entries_of_this_week_only():
    entries = weekly.read_learning_log(LOG, SINCE.date())
    assert [e["date"] for e in entries] == [date(2026, 11, 10), date(2026, 11, 12)]
    assert entries[0]["learned"] == "filters in the URL can be shared."
    assert "got unblocked by" not in entries[0]                     # empty field left out
    assert entries[1]["next"] == "daily PCA email."


def make_report(problems=()):
    entries = weekly.read_learning_log(LOG, SINCE.date())
    commits = [{"hash": "a" * 40, "short": "aaaaaaa", "date": "2026-11-12", "subject": "Add tick.py"}]
    return weekly.build_report(NOW, commits, weekly.closed_this_week(ISSUES, SINCE),
                               [], ("On track", "no blocked issues"), entries,
                               "https://github.com/x/y", "https://dash.example", date(2026, 10, 30), problems)


def test_report_sections_and_links():
    report = make_report()
    sections = {title: entries for title, entries, _ in report["sections"]}
    assert [e["text"] for e in sections["Done this week"]][:2] == [
        "Issue #7: Hourly pipeline", "Pull request #9: Dashboard filters"]
    assert sections["Done this week"][2]["url"] == "https://github.com/x/y/commit/" + "a" * 40
    assert sections["Blockers"][0]["text"] == "red imports in VS Code. → not solved yet"
    assert report["timeline"].startswith("Day 15 of 30 · Week 3")

    page = weekly.render_html(report)
    for text in ["On track", "Done this week", "Learned this week", "Blockers", "Next week",
                 "https://dash.example", "https://github.com/x/y/issues/7"]:
        assert text in page
    assert "$" not in page.replace("$$", "")                          # every placeholder filled
    assert weekly.subject(report) == "Weekly progress · Fri 13 Nov 2026 · On track"


def test_report_says_what_it_could_not_read():
    report = make_report(problems=["GitHub issues and milestones (HTTP Error 403)"])
    assert "Could not read: GitHub issues and milestones (HTTP Error 403)" in weekly.render_text(report)


def test_send_builds_a_text_and_html_email(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("smtp.gmail.com", 587)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, user, password): assert user == "me@gmail.com"
        def send_message(self, message): sent.append(message)

    monkeypatch.setattr(weekly.smtplib, "SMTP", FakeSMTP)
    settings = {"EMAIL_SERVER_HOST": "smtp.gmail.com", "EMAIL_SERVER_PORT": "587",
                "EMAIL_SERVER_USER": "me@gmail.com", "EMAIL_SERVER_PASSWORD": "app-password",
                "EMAIL_FROM": "me@gmail.com", "EMAIL_TO": "boss@example.com"}
    weekly.send(make_report(), settings)
    message = sent[0]
    assert message["To"] == "boss@example.com"
    assert [p.get_content_type() for p in message.iter_parts()] == ["text/plain", "text/html"]


def test_main_dry_run_with_github(monkeypatch, tmp_path, capsys):
    answers = {"issues?state=closed": ISSUES, "issues?state=open": [], "milestones": []}
    monkeypatch.setattr(weekly.GitHub, "get",
                        lambda self, path: next(v for k, v in answers.items() if path.startswith(k)))
    monkeypatch.setattr(weekly, "PREVIEW", tmp_path / "preview.html")
    monkeypatch.setenv("GITHUB_REPOSITORY", "x/y")
    monkeypatch.setattr(sys, "argv", ["send_weekly_progress.py", "--dry-run"])
    weekly.main()
    out = capsys.readouterr().out
    assert "Status: On track" in out and "Issue #7: Hourly pipeline" in out
    assert (tmp_path / "preview.html").exists()