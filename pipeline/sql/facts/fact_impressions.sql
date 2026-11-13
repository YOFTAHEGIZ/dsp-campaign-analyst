-- Fact table: impressions.
-- Grain: one row per impression (imp_key).
--
-- Clicks and conversions are attached to the impression they came from
-- (from the linked models), so every rate can be computed from this one table.
-- Prices are per 1,000 impressions (like a CPM), so cost = paying_price / 1000.
--
-- Columns from the log NOT kept here (see the data decisions document):
--   log_type (always 1 in this file), ip, url, anonymous_url_id, domain,
--   ad_slot_id, key_page_url: IDs and URLs, not reporting fields.
--
-- Built as a VIEW: it is computed when read, so 12 million rows are not
-- stored a second time on disk.

WITH clicks AS (
    SELECT imp_key, COUNT(*) AS click_events
    FROM int_clicks_linked
    WHERE imp_key IS NOT NULL
    GROUP BY imp_key
),

conversions AS (
    SELECT
        imp_key,
        COUNT(*) AS conversion_events,
        MAX(CASE WHEN conversion_type = 'post-click' THEN 1 ELSE 0 END) AS post_click
    FROM int_conversions_linked
    WHERE imp_key IS NOT NULL
    GROUP BY imp_key
)

SELECT
    i.imp_key,
    i.bid_id,
    i.ipinyou_id AS user_id,

    -- When
    i.impression_datetime,
    i.impression_date,
    i.hour,

    -- Who bought it (in iPinYou each advertiser runs one campaign)
    i.advertiser_id,
    i.advertiser_id AS campaign_id,
    i.creative_id,

    -- Where it was shown
    i.ad_exchange,
    i.region,
    i.city,
    i.ad_slot_width,
    i.ad_slot_height,
    i.ad_slot_visibility,
    i.ad_slot_format,

    -- Device, from the user agent
    COALESCE(u.device, 'unknown') AS device,
    COALESCE(u.os, 'unknown') AS os,
    COALESCE(u.browser, 'unknown') AS browser,
    i.user_tags,

    -- Prices
    i.ad_slot_floor_price AS floor_price,
    CASE
        WHEN i.ad_slot_floor_price IS NULL THEN 'unknown'
        WHEN i.ad_slot_floor_price = 0 THEN '0'
        WHEN i.ad_slot_floor_price <= 10 THEN '1-10'
        WHEN i.ad_slot_floor_price <= 50 THEN '11-50'
        WHEN i.ad_slot_floor_price <= 100 THEN '51-100'
        WHEN i.ad_slot_floor_price <= 200 THEN '101-200'
        ELSE '200+'
    END AS floor_band,                                                  -- same bands as stg_bid_summary
    i.bidding_price,
    i.paying_price,
    i.paying_price / 1000.0 AS cost,

    -- What happened after the impression
    CASE WHEN c.imp_key IS NOT NULL THEN 1 ELSE 0 END AS clicked,      -- 0/1, for CTR
    COALESCE(c.click_events, 0) AS click_events,                       -- repeat clicks counted
    CASE WHEN v.imp_key IS NOT NULL THEN 1 ELSE 0 END AS converted,
    COALESCE(v.post_click, 0) AS post_click_converted,
    COALESCE(v.conversion_events, 0) AS conversion_events

FROM stg_impressions i
LEFT JOIN clicks c ON i.imp_key = c.imp_key
LEFT JOIN conversions v ON i.imp_key = v.imp_key
LEFT JOIN int_user_agents u ON i.user_agent = u.user_agent;