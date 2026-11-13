-- Intermediate model: every conversion, linked to the impression it came from.
-- One row per conversion. Same linking rule as int_clicks_linked (see that file).
--
-- conversion_type:
--   post-click     = the impression was clicked before the conversion
--   post-view      = the ad was shown but not clicked, and the user still converted
--   no impression  = no impression found for this bid_id

WITH conversions AS (
    SELECT
        ROW_NUMBER() OVER (ORDER BY bid_id, conversion_datetime, ipinyou_id) AS conversion_id,
        *
    FROM stg_conversions
),

candidates AS (
    SELECT imp_key, bid_id, ipinyou_id, impression_datetime, impression_date
    FROM stg_impressions
    WHERE bid_id IN (SELECT bid_id FROM stg_conversions)
),

same_user AS (
    SELECT v.conversion_id, i.imp_key
    FROM conversions v
    ASOF JOIN candidates i
        ON v.bid_id = i.bid_id
        AND v.ipinyou_id = i.ipinyou_id
        AND v.conversion_datetime >= i.impression_datetime
),

same_bid AS (
    SELECT v.conversion_id, i.imp_key
    FROM conversions v
    ASOF JOIN candidates i
        ON v.bid_id = i.bid_id
        AND v.conversion_datetime >= i.impression_datetime
),

nearest AS (
    SELECT
        v.conversion_id,
        ARG_MIN(i.imp_key, ABS(EPOCH(v.conversion_datetime) - EPOCH(i.impression_datetime))) AS imp_key
    FROM conversions v
    JOIN candidates i ON v.bid_id = i.bid_id
    GROUP BY v.conversion_id
),

linked AS (
    SELECT
        v.*,
        COALESCE(u.imp_key, b.imp_key, n.imp_key) AS imp_key,
        CASE
            WHEN u.imp_key IS NOT NULL THEN 1
            WHEN b.imp_key IS NOT NULL THEN 2
            WHEN n.imp_key IS NOT NULL THEN 3
            ELSE 4
        END AS link_rule
    FROM conversions v
    LEFT JOIN same_user u ON v.conversion_id = u.conversion_id
    LEFT JOIN same_bid  b ON v.conversion_id = b.conversion_id
    LEFT JOIN nearest   n ON v.conversion_id = n.conversion_id
),

-- The first click on each impression (from the linked clicks)
first_click AS (
    SELECT imp_key, MIN(click_datetime) AS first_click_datetime
    FROM int_clicks_linked
    WHERE imp_key IS NOT NULL
    GROUP BY imp_key
)

SELECT
    l.conversion_id,
    l.imp_key,
    l.bid_id,
    l.ipinyou_id,
    l.advertiser_id,
    l.conversion_datetime,
    l.conversion_date,

    i.impression_datetime,
    i.impression_date,
    f.first_click_datetime,

    CASE
        WHEN l.imp_key IS NULL THEN 'no impression'
        WHEN f.first_click_datetime <= l.conversion_datetime THEN 'post-click'
        ELSE 'post-view'
    END AS conversion_type,

    l.link_rule
FROM linked l
LEFT JOIN candidates i ON l.imp_key = i.imp_key
LEFT JOIN first_click f ON l.imp_key = f.imp_key;