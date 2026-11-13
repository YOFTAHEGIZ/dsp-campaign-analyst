-- Intermediate model: every click, linked to the impression it came from.
-- One row per click.
--
-- Why this is needed: bid_id is not unique in the impression log (the same bid_id
-- can show up with a different user and time), so "join on bid_id" can attach a
-- click to the wrong impression, or to two impressions at once.
--
-- Rule, tried in order (link_rule says which one matched):
--   1 = same bid_id AND same user, the latest impression at or before the click
--   2 = same bid_id (user missing or different), the latest impression at or before the click
--   3 = same bid_id, the impression nearest in time (the logs' clocks can differ a little)
--   4 = no impression with this bid_id: the click is kept, imp_key stays NULL
--
-- ASOF JOIN finds "the latest row at or before" in one step.

WITH clicks AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY bid_id, click_datetime, ipinyou_id) AS click_id,
        *
    FROM stg_clicks
),

-- Only impressions whose bid_id was clicked: a small table, so the joins are fast
candidates AS (
    SELECT imp_key, bid_id, ipinyou_id, impression_datetime, impression_date
    FROM stg_impressions
    WHERE bid_id IN (SELECT bid_id FROM stg_clicks)
),

same_user AS (
    SELECT c.click_id, i.imp_key
    FROM clicks c
    ASOF JOIN candidates i
        ON c.bid_id = i.bid_id
        AND c.ipinyou_id = i.ipinyou_id
        AND c.click_datetime >= i.impression_datetime
),

same_bid AS (
    SELECT c.click_id, i.imp_key
    FROM clicks c
    ASOF JOIN candidates i
        ON c.bid_id = i.bid_id
        AND c.click_datetime >= i.impression_datetime
),

nearest AS (
    SELECT
        c.click_id,
        ARG_MIN(i.imp_key, ABS(EPOCH(c.click_datetime) - EPOCH(i.impression_datetime))) AS imp_key
    FROM clicks c
    JOIN candidates i ON c.bid_id = i.bid_id
    GROUP BY c.click_id
),

linked AS (
    SELECT
        c.*,
        COALESCE(u.imp_key, b.imp_key, n.imp_key) AS imp_key,
        CASE
            WHEN u.imp_key IS NOT NULL THEN 1
            WHEN b.imp_key IS NOT NULL THEN 2
            WHEN n.imp_key IS NOT NULL THEN 3
            ELSE 4
        END AS link_rule
    FROM clicks c
    LEFT JOIN same_user u ON c.click_id = u.click_id
    LEFT JOIN same_bid  b ON c.click_id = b.click_id
    LEFT JOIN nearest   n ON c.click_id = n.click_id
)

SELECT
    l.click_id,
    l.imp_key,
    l.bid_id,
    l.ipinyou_id,
    l.advertiser_id,
    l.click_datetime,
    l.click_date,

    -- The impression's time: clicks are reported on the day the ad was shown
    i.impression_datetime,
    i.impression_date,

    l.link_rule
FROM linked l
LEFT JOIN candidates i ON l.imp_key = i.imp_key;