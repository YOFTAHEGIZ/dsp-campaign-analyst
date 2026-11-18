-- Read-only database role for the AI features (week 3).
--
-- The AI ("What changed", insights, "Ask the data") connects as ai_reader, never as the owner.
-- ai_reader can only SELECT from the dashboard tables and views listed below: it cannot change data,
-- create tables, or read anything else (load_log, llm_calls, ...).
--
-- IMPORTANT: create the role with SQL (part A), NOT with the "Add role" button in the Neon console.
-- Roles made with the button join neon_superuser, which can read and write every table.
--
-- How to use (Neon console > Postgres database > SQL Editor, as neondb_owner):
--   1. Make a strong password on your laptop:  python -c "import secrets; print(secrets.token_urlsafe(24))"
--   2. Replace PASTE_PASSWORD_HERE below with it IN THE EDITOR ONLY. Never save the password in this file.
--   3. Run everything. The first check should list 9 rows, all SELECT; the second, 0 rows.
--   4. .env and Vercel: AI_DATABASE_URL = your NEON_DATABASE_URL with
--      "neondb_owner:<old password>" replaced by "ai_reader:<new password>". Never commit it.

-- A. Create the role
CREATE ROLE ai_reader WITH LOGIN PASSWORD 'PASTE_PASSWORD_HERE';

-- B. Nothing by default
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ai_reader;
REVOKE CREATE ON SCHEMA public FROM ai_reader;
GRANT USAGE ON SCHEMA public TO ai_reader;

-- C. Read access to the dashboard tables only
GRANT SELECT ON
    daily_campaign,
    daily_auction,
    hourly_pacing,
    dim_advertiser,
    dim_campaign,
    dim_date,
    pipeline_status,
    v_campaign_kpis,
    v_auction_kpis
TO ai_reader;

-- D. Every session read-only, and no query longer than 5 seconds
--    (allowed because neondb_owner created this role)
ALTER ROLE ai_reader SET default_transaction_read_only = on;
ALTER ROLE ai_reader SET statement_timeout = '5s';

-- E. Checks
-- E1: 9 rows, all SELECT
SELECT table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'ai_reader'
ORDER BY table_name;

-- E2: 0 rows (ai_reader belongs to no group, so it has no hidden extra rights)
SELECT r.rolname AS member_of
FROM pg_auth_members m
JOIN pg_roles r ON r.oid = m.roleid
JOIN pg_roles u ON u.oid = m.member
WHERE u.rolname = 'ai_reader';