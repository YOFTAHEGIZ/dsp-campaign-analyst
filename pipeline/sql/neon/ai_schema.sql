-- Tables for the AI layer (week 3). Created by the owner role, never by ai_reader.
-- llm.py runs this file before it logs the first call. Safe to run again.

-- Every LLM call: what was asked, what came back, the judge's verdict, time and provider.
-- One run_id groups the calls of one answer: generate -> judge (-> generate again -> judge).
CREATE TABLE IF NOT EXISTS llm_calls (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    purpose TEXT NOT NULL,          -- what_changed | insights | ask | test
    step TEXT NOT NULL,             -- generate | judge
    attempt INTEGER NOT NULL,       -- 1 = first try, 2 = regenerated after a fail
    provider TEXT NOT NULL,         -- gemini | groq | cohere
    model TEXT NOT NULL,
    prompt TEXT NOT NULL,
    output TEXT,
    verdict TEXT,                   -- judge rows: pass | fail
    reason TEXT,                    -- judge rows: why
    latency_ms INTEGER,
    error TEXT                      -- filled when the call failed
);

CREATE INDEX IF NOT EXISTS llm_calls_run ON llm_calls (run_id);
CREATE INDEX IF NOT EXISTS llm_calls_created ON llm_calls (created_at);

-- ---- "What changed" ----

-- Unusual hours, found by anomalies.py after every tick (recomputed from hourly_pacing each time).
-- Each campaign-hour is compared with the SAME hour of the day on that campaign's OTHER days,
-- so an evening peak is not flagged just for being evening.
CREATE TABLE IF NOT EXISTS anomalies (
    advertiser_id INTEGER NOT NULL,
    report_date DATE NOT NULL,
    hour INTEGER NOT NULL,              -- 0..23
    metric TEXT NOT NULL,               -- ctr | win_rate | impressions | spend | cpm
    value DOUBLE PRECISION NOT NULL,    -- this hour
    baseline DOUBLE PRECISION NOT NULL, -- same hour, other days
    z DOUBLE PRECISION NOT NULL,        -- how many noise units away (|z| >= 3 is flagged)
    change DOUBLE PRECISION NOT NULL,   -- (value - baseline) / baseline, e.g. 0.4 = 40% higher
    direction TEXT NOT NULL,            -- up | down
    baseline_days INTEGER NOT NULL,     -- how many other days the baseline uses
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (advertiser_id, report_date, hour, metric)
);

-- One judged explanation per EVENT (step 4): neighbouring flagged hours of the same advertiser on the
-- same day are one event (e.g. "3476 stopped at 11:00" covers 11:00-23:00), explained once.
-- hour = first hour of the event, end_hour = last. fingerprint records which numbers were explained:
-- if a later tick changes them, the explanation is made again.
CREATE TABLE IF NOT EXISTS explanations (
    advertiser_id INTEGER NOT NULL,
    report_date DATE NOT NULL,
    hour INTEGER NOT NULL,
    end_hour INTEGER,
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,               -- pass (shown) | withheld (not shown, note says why)
    headline TEXT,
    drivers JSONB,                      -- list of short strings
    confidence TEXT,                    -- high | medium | low
    note TEXT,
    facts JSONB,                        -- the query results the model and the judge saw
    sql JSONB,                          -- the queries behind them, shown on the dashboard
    provider TEXT,
    run_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (advertiser_id, report_date, hour)
);

ALTER TABLE explanations ADD COLUMN IF NOT EXISTS end_hour INTEGER;

-- The AI's read-only role may read these two (they are dashboard tables), never llm_calls.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_reader') THEN
        GRANT SELECT ON anomalies, explanations TO ai_reader;
    END IF;
END $$;