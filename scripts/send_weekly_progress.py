"""
Weekly progress email: sent to the manager every Friday at 18:00 East Africa Time
by .github/workflows/weekly-progress.yml.

    python scripts/send_weekly_progress.py              # build and send
    python scripts/send_weekly_progress.py --dry-run    # build only, save reports/weekly_progress_preview.html

Built from three sources, as the challenge asks:
  1. commits of the last 7 days          (git log)
  2. issues and pull requests closed      (GitHub API, with the workflow's GITHUB_TOKEN)
     in the last 7 days, plus open issues, labels and milestones for the status
  3. LEARNING_LOG.md entries of the last 7 days
     (## YYYY-MM-DD: title, then - **Learned:** / - **Blocked by:** / - **Got unblocked by:** / - **Next:**)

Sections (from the challenge PDF): Status, Done this week, Learned this week, Blockers,
Next week, Links.

Status, against the timeline:
  Blocked          an open issue has the label "blocked"
  Slightly behind  a milestone's due date has passed and it still has open issues
  On track         otherwise
  PROGRESS_STATUS ("on track", "slightly behind" or "blocked") overrides it, if you set it.

Never a wrong report: if a source cannot be read, the email says so instead of guessing.
If the email cannot be sent, the script fails, and GitHub emails the repo owner about the failed run.

Settings (GitHub secrets): EMAIL_SERVER_HOST, EMAIL_SERVER_PORT, EMAIL_SERVER_USER,
EMAIL_SERVER_PASSWORD, EMAIL_FROM, EMAIL_TO.
Optional (GitHub variables): DASHBOARD_URL, CHALLENGE_START_DATE (YYYY-MM-DD, day 1), PROGRESS_STATUS.
Set by GitHub Actions: GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_SERVER_URL.
"""

import argparse
import html
import json
import os
import re
import smtplib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from string import Template
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "scripts" / "templates" / "weekly_progress.html"
LEARNING_LOG = PROJECT_ROOT / "LEARNING_LOG.md"
PREVIEW = PROJECT_ROOT / "reports" / "weekly_progress_preview.html"
TIMEZONE = ZoneInfo("Africa/Addis_Ababa")

# The challenge timeline (term 1): week, first day, last day, focus, end-of-week result
TIMELINE = [
    (1, 1, 7, "Data engineering, Docker, adtech basics, weekly email",
     "Live Vercel URL with real data; first progress email sent"),
    (2, 8, 14, "Data analysis and math, adtech, dashboard tabs",
     "Data story with five findings; performance and auction tabs live"),
    (3, 15, 21, "LLM insights, What changed, Ask the data", "AI tabs live, test set passing"),
    (4, 22, 30, "Daily PCA email, polish, CI", "Daily report arriving every morning; everything delivered"),
]

MAX_COMMITS = 15  # keep the email short: older commits become "and N more"

STATUS_STYLE = {  # background, text colour
    "On track": ("#e6f4ea", "#1e7b34"),
    "Slightly behind": ("#fdf3dc", "#9a6700"),
    "Blocked": ("#fde8e8", "#b42318"),
    "Not checked": ("#f1f1ef", "#52514e"),
}


# ---- 1. Commits -------------------------------------------------------------------

def get_commits(since):
    """Commits since `since` (a datetime), newest first."""
    result = subprocess.run(
        ["git", "log", f"--since={since.isoformat()}", "--no-merges",
         "--pretty=format:%H%x09%h%x09%ad%x09%s", "--date=short"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
    )
    commits = []
    for line in result.stdout.splitlines():
        full, short, day, subject_ = line.split("\t", 3)
        commits.append({"hash": full, "short": short, "date": day, "subject": subject_})
    return commits


# ---- 2. GitHub issues, pull requests, milestones -----------------------------------

class GitHub:
    def __init__(self, repository, token, api="https://api.github.com"):
        self.repository, self.token, self.api = repository, token, api

    def get(self, path):
        request = urllib.request.Request(f"{self.api}/repos/{self.repository}/{path}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)


def closed_this_week(items, since):
    """Issues closed and pull requests merged since `since`. The issues API returns both."""
    done = []
    for item in items:
        closed_at = item.get("closed_at")
        if not closed_at or datetime.fromisoformat(closed_at.replace("Z", "+00:00")) < since:
            continue
        pull = item.get("pull_request")
        if pull is not None and not pull.get("merged_at"):
            continue  # a pull request closed without merging is not "done"
        done.append({"number": item["number"], "title": item["title"], "url": item["html_url"],
                     "kind": "Pull request" if pull is not None else "Issue"})
    return done


def open_issues(items):
    return [{"number": i["number"], "title": i["title"], "url": i["html_url"],
             "labels": [label["name"].lower() for label in i.get("labels", [])]}
            for i in items if "pull_request" not in i]


def work_out_status(open_items, milestones, now, override=None):
    """(status, reason) against the timeline. See the top of this file."""
    if override:
        status = {"on track": "On track", "slightly behind": "Slightly behind",
                  "blocked": "Blocked"}.get(override.strip().lower())
        if status:
            return status, "set by hand (PROGRESS_STATUS)"
    blocked = [i for i in open_items if "blocked" in i["labels"]]
    if blocked:
        return "Blocked", f"{len(blocked)} open issue(s) labelled blocked: " + \
            ", ".join(f"#{i['number']}" for i in blocked)
    late = [m for m in milestones
            if m.get("due_on") and m.get("open_issues", 0) > 0
            and datetime.fromisoformat(m["due_on"].replace("Z", "+00:00")) < now]
    if late:
        return "Slightly behind", "past due: " + ", ".join(
            f"{m['title']} ({m['open_issues']} open)" for m in late)
    return "On track", "no blocked issues and no overdue milestones"


# ---- 3. Learning log --------------------------------------------------------------

HEADING = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*[:\-–—]?\s*(.*)$")
FIELD = re.compile(r"^\s*[-*]\s*\*\*\s*(Learned|Blocked by|Got unblocked by|Next)\s*:?\s*\*\*\s*:?\s*(.*)$",
                   re.IGNORECASE)


def read_learning_log(text, since_day):
    """Entries dated on or after since_day, oldest first:
    [{"date", "title", "learned", "blocked by", "got unblocked by", "next"}] (empty fields left out)."""
    entries, current = [], None
    for line in text.splitlines():
        heading = HEADING.match(line.strip())
        if heading:
            try:
                day = date.fromisoformat(heading.group(1))
            except ValueError:
                current = None
                continue
            current = {"date": day, "title": heading.group(2).strip()} if day >= since_day else None
            if current:
                entries.append(current)
            continue
        if line.startswith("## "):
            current = None  # another section, e.g. "## Resources"
            continue
        field = FIELD.match(line)
        if current is not None and field and field.group(2).strip():
            current[field.group(1).lower()] = field.group(2).strip()
    return sorted(entries, key=lambda e: e["date"])


# ---- The report ----------------------------------------------------------------

def timeline_line(start, today):
    if not start:
        return ""
    day = (today - start).days + 1
    for week, first, last, focus, result in TIMELINE:
        if first <= day <= last:
            return f"Day {day} of 30 · Week {week}: {focus}. End-of-week goal: {result}."
    return f"Day {day} of the challenge."


def build_report(now, commits, closed, open_items, status, log_entries, repo_url, dashboard_url,
                 start=None, problems=()):
    """All the content of the email, as plain data (no HTML here)."""
    def commit_url(c):
        return f"{repo_url}/commit/{c['hash']}" if repo_url else ""

    done = [{"text": f"{i['kind']} #{i['number']}: {i['title']}", "url": i["url"]} for i in closed]
    done += [{"text": f"{c['date']} · {c['subject']} ({c['short']})", "url": commit_url(c)}
             for c in commits[:MAX_COMMITS]]
    if len(commits) > MAX_COMMITS:
        done.append({"text": f"and {len(commits) - MAX_COMMITS} more commits",
                     "url": f"{repo_url}/commits" if repo_url else ""})

    learned = [{"text": e["learned"], "note": f"{e['date']:%a %d %b}"} for e in log_entries if e.get("learned")]
    blockers = [{"text": e["blocked by"] + (f" → handled: {e['got unblocked by']}" if e.get("got unblocked by")
                                            else " → not solved yet"),
                 "note": f"{e['date']:%a %d %b}"} for e in log_entries if e.get("blocked by")]
    next_week = [{"text": e["next"], "note": "from the learning log"} for e in log_entries[-2:] if e.get("next")]
    next_week += [{"text": f"#{i['number']}: {i['title']}", "url": i["url"]}
                  for i in open_items if "blocked" not in i["labels"]][:5]

    return {
        "report_date": f"{now:%a %d %b %Y}",
        "status": status[0], "status_reason": status[1],
        "timeline": timeline_line(start, now.date()),
        "sections": [
            ("Done this week", done, "No commits, closed issues or merged pull requests this week."),
            ("Learned this week", learned, "No learning log entries this week."),
            ("Blockers", blockers, "No blockers recorded this week."),
            ("Next week", next_week, "Nothing planned yet: add open issues or a Next: line in the learning log."),
        ],
        "repo_url": repo_url, "dashboard_url": dashboard_url,
        "problems": list(problems),
    }


def subject(report):
    return f"Weekly progress · {report['report_date']} · {report['status']}"


def render_html(report):
    def item(entry):
        text = html.escape(entry["text"])
        if entry.get("url"):
            text = f'<a href="{html.escape(entry["url"])}" style="color:#2a78d6;text-decoration:none;">{text}</a>'
        note = f' <span style="color:#8a8984;font-size:13px;">· {html.escape(entry["note"])}</span>' \
            if entry.get("note") else ""
        return f'<li style="margin:0 0 6px;">{text}{note}</li>'

    sections = []
    for title, entries, empty in report["sections"]:
        body = (f'<ul style="margin:6px 0 0;padding-left:18px;">{"".join(item(e) for e in entries)}</ul>'
                if entries else f'<div style="color:#8a8984;margin-top:4px;">{html.escape(empty)}</div>')
        sections.append(f'<tr><td style="padding:12px 20px 4px;"><div style="font-weight:700;">'
                        f'{html.escape(title)}</div>{body}</td></tr>')
    if report["problems"]:
        sections.append('<tr><td style="padding:12px 20px 4px;"><div style="padding:10px 12px;border-radius:6px;'
                        'background:#fdf3dc;font-size:13px;">Could not read: '
                        + html.escape("; ".join(report["problems"])) + "</div></td></tr>")

    background, color = STATUS_STYLE[report["status"]]
    return Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        subject=html.escape(subject(report)), report_date=html.escape(report["report_date"]),
        status=html.escape(report["status"]), status_reason=html.escape(report["status_reason"]),
        status_bg=background, status_color=color, timeline=html.escape(report["timeline"]),
        sections="\n".join(sections),
        dashboard_url=html.escape(report["dashboard_url"] or report["repo_url"] or "#"),
        repo_url=html.escape(report["repo_url"] or "#"),
        sources_note="",
    )


def render_text(report):
    """The plain-text version, for email apps that do not show HTML."""
    lines = [f"Weekly progress · {report['report_date']}",
             f"Status: {report['status']} ({report['status_reason']})"]
    if report["timeline"]:
        lines.append(report["timeline"])
    for title, entries, empty in report["sections"]:
        lines += ["", title.upper()]
        lines += [f"- {e['text']}" + (f" ({e['url']})" if e.get("url") else "") for e in entries] or [empty]
    if report["problems"]:
        lines += ["", "Could not read: " + "; ".join(report["problems"])]
    lines += ["", "LINKS", f"Dashboard: {report['dashboard_url'] or 'not set'}", f"Repo: {report['repo_url']}"]
    return "\n".join(lines)


# ---- Sending ----------------------------------------------------------------------

def send(report, settings, attempts=2):
    message = EmailMessage()
    message["Subject"] = subject(report)
    message["From"] = settings["EMAIL_FROM"]
    message["To"] = settings["EMAIL_TO"]
    message.set_content(render_text(report))
    message.add_alternative(render_html(report), subtype="html")

    for attempt in range(1, attempts + 1):
        try:
            with smtplib.SMTP(settings["EMAIL_SERVER_HOST"], int(settings["EMAIL_SERVER_PORT"]), timeout=60) as server:
                server.starttls()
                server.login(settings["EMAIL_SERVER_USER"], settings["EMAIL_SERVER_PASSWORD"])
                server.send_message(message)
            return
        except (smtplib.SMTPException, OSError) as error:
            if attempt == attempts:
                raise
            print(f"Sending failed ({error}); trying again in 30 seconds")
            time.sleep(30)


# ---- Main ------------------------------------------------------------------------

SECRETS = ["EMAIL_SERVER_HOST", "EMAIL_SERVER_PORT", "EMAIL_SERVER_USER", "EMAIL_SERVER_PASSWORD",
           "EMAIL_FROM", "EMAIL_TO"]


def main():
    parser = argparse.ArgumentParser(description="Build and send the weekly progress email")
    parser.add_argument("--dry-run", action="store_true",
                        help="do not send; save reports/weekly_progress_preview.html")
    args = parser.parse_args()

    settings = {name: os.getenv(name, "") for name in SECRETS}
    missing = [name for name, value in settings.items() if not value]
    if missing and not args.dry_run:
        sys.exit("Missing settings (GitHub secrets): " + ", ".join(missing))

    now = datetime.now(TIMEZONE)
    since = now - timedelta(days=7)
    repository = os.getenv("GITHUB_REPOSITORY", "")
    repo_url = f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/{repository}" if repository else ""
    start = os.getenv("CHALLENGE_START_DATE", "").strip()
    override = os.getenv("PROGRESS_STATUS", "")
    problems = []

    commits = get_commits(since)  # if git fails, the run fails: better than an empty "Done"

    closed, open_items = [], []
    status = work_out_status([], [], now, override) if override else ("Not checked", "GitHub issues could not be read")
    if repository:
        github = GitHub(repository, os.getenv("GITHUB_TOKEN", ""))
        try:
            since_utc = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            closed = closed_this_week(github.get(f"issues?state=closed&since={since_utc}&per_page=100"), since)
            open_items = open_issues(github.get("issues?state=open&per_page=100"))
            milestones = github.get("milestones?state=open&per_page=100")
            status = work_out_status(open_items, milestones, now, override)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            problems.append(f"GitHub issues and milestones ({error})")
    else:
        problems.append("GitHub issues (GITHUB_REPOSITORY is not set; GitHub Actions sets it)")

    log_entries = []
    if LEARNING_LOG.exists():
        log_entries = read_learning_log(LEARNING_LOG.read_text(encoding="utf-8"), since.date())
    else:
        problems.append("LEARNING_LOG.md (file not found)")

    report = build_report(now, commits, closed, open_items, status, log_entries, repo_url,
                          os.getenv("DASHBOARD_URL", ""), date.fromisoformat(start) if start else None, problems)

    print(render_text(report))
    if args.dry_run:
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        PREVIEW.write_text(render_html(report), encoding="utf-8")
        print(f"\nDry run: nothing sent. Preview saved to {PREVIEW}")
        return
    send(report, settings)
    print(f"\nWeekly progress email sent to {settings['EMAIL_TO']}.")


if __name__ == "__main__":
    main()