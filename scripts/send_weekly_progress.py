import os
import subprocess
import smtplib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from email.message import EmailMessage

# Find the project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Read credentials from environment variables
email_username = os.environ["EMAIL_SERVER_USER"]
email_password = os.environ["EMAIL_SERVER_PASSWORD"]
email_from = os.environ["EMAIL_FROM"]
email_to = os.environ["EMAIL_TO"]

smtp_host = os.environ["EMAIL_SERVER_HOST"]
smtp_port = int(os.environ["EMAIL_SERVER_PORT"])

# Get commits from the last seven days
result = subprocess.run(
    ["git", "log", "--since=7.days", "--pretty=format:- %h %s"],
    cwd=PROJECT_ROOT,
    capture_output=True,
    text=True,
    check=True,
)

commits = result.stdout.strip() or "No new commits recorded this week."

# Find generated validation reports
reports_dir = PROJECT_ROOT / "reports"
reports = (
    sorted(path.name for path in reports_dir.glob("*.csv"))
    if reports_dir.exists()
    else []
)

report_text = (
    "\n".join(f"- {name}" for name in reports)
    if reports
    else "No CSV reports found."
)

# Prepare the email
today = datetime.now(ZoneInfo("Africa/Addis_Ababa"))

message = EmailMessage()
message["Subject"] = f"Weekly AI Campaign Analyst Progress - {today:%Y-%m-%d}"
message["From"] = email_from
message["To"] = email_to

message.set_content(f"""
Hello,

Here is the weekly progress report for the AI Campaign Analyst project.

PROJECT: AI Campaign Analyst
ADVERTISER: 1458
REPORT DATE: {today:%Y-%m-%d}

GITHUB ACTIVITY (LAST 7 DAYS)
{commits}

AVAILABLE VALIDATION REPORTS
{report_text}

PROJECT MILESTONES
- iPinYou data processed using DuckDB and Parquet.
- SQL staging transformations and daily campaign mart created.
- Dockerized pipeline implemented.
- Campaign summaries loaded into Neon PostgreSQL.
- Next.js dashboard deployed to Vercel.
- Notebook 02 funnel validation completed.

Regards,
AI Campaign Analyst Progress Automation
""")

# Send using Gmail SMTP
with smtplib.SMTP(smtp_host, smtp_port) as server:
    server.starttls()
    server.login(email_username, email_password)
    server.send_message(message)

print("Weekly progress email sent successfully.")