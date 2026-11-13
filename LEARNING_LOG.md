# Learning Log

What I learned, what blocked me, and how I got unblocked. Newest entry first.
The weekly progress email reads the entries of the last 7 days, so keep this format:
a heading "## YYYY-MM-DD: title", then the four lines below (leave a line empty if it does not apply).

## 2026-11-13: Weekly progress email

- **Learned:** GitHub Actions can run a script on a schedule; cron runs in UTC, so 18:00 in Addis is 15:00.
- **Blocked by:** my first email was plain text and did not use issues or the learning log.
- **Got unblocked by:** building it from commits, closed issues and this log, with an HTML template for phones.
- **Next:** create GitHub issues and weekly milestones so the status is checked against the timeline.

## 2026-11-13: Hourly pipeline with a watermark

- **Learned:** a watermark is a bookmark that lets an hourly pipeline continue where it stopped and run safely twice.
- **Blocked by:** a click can arrive after its impression, sometimes on the next day.
- **Got unblocked by:** each tick also reloads the day of the impressions that its clicks belong to.
- **Next:** run the scheduler in Docker and check the dashboard updates by itself.

## 2026-11-11: Dashboard with filters

- **Learned:** keeping the filters in the URL makes a dashboard view easy to share.
- **Blocked by:** red import errors in VS Code and an SSL warning from the pg library.
- **Got unblocked by:** restarting the TypeScript server, and turning on SSL in the code instead of the URL.
- **Next:** deploy to Vercel and check the live URL shows real numbers.

## 2026-11-11: Daily tables in Neon

- **Learned:** store counts and sums only, and compute rates as a ratio of sums when they are shown.
- **Blocked by:** not enough disk to keep the bid logs of all 5 advertisers.
- **Got unblocked by:** counting the bids while reading the files and keeping only the small summary.
- **Next:** build the dashboard on these tables.

## 2026-11-11: Data model and data decisions

- **Learned:** fact tables hold events, dimension tables describe them (advertiser, campaign, date).
- **Blocked by:** bid_id is not unique, so joining clicks on bid_id alone links some to the wrong impression.
- **Got unblocked by:** linking each click to the latest impression with the same bid_id and user (ASOF JOIN).
- **Next:** daily auction and hourly pacing tables.

## 2026-11-11: Pipeline for all 7 days

- **Learned:** a .bz2 file can be read as a stream, so nothing has to be decompressed to disk.
- **Blocked by:** some conversion rows have 23 columns instead of 24.
- **Got unblocked by:** reading those files line by line and filling the missing column with null.
- **Next:** link clicks and conversions to their impressions.

## 2026-11-10: Task 2 analysis, notebooks 01-10

- **Learned:** bid_id is not unique: the same ID can belong to different users, so I match events by bid ID, user and time.
- **Blocked by:** not enough disk space to decompress the logs, and notebooks locking the database when two were open.
- **Got unblocked by:** reading the .bz2 files as a stream into Parquet, opening the database read-only, and closing other notebooks.
- **Next:** rebuild Task 1 properly using what the analysis found.

## 2026-11-06: Dockerized pipeline, Neon and the first dashboard

- **Learned:** Docker runs the same pipeline on any computer; secrets go in .env, never in the code.
- **Blocked by:**
- **Got unblocked by:**
- **Next:** analyse the data (Task 2).

## 2026-10-28: Started the project

- **Learned:** the iPinYou logs are tab-separated with no header; missing values are the text "null".
- **Blocked by:** not enough free disk space to decompress the .bz2 files.
- **Got unblocked by:**
- **Next:** load the data into DuckDB.

