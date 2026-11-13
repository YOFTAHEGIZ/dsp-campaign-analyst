-- Dimension table: campaigns.
-- Grain: one row per campaign.
-- In iPinYou each advertiser runs one campaign per season, so campaign_id is the
-- advertiser_id. Keeping a separate table means the dashboard and the facts do not
-- have to change if an advertiser ever runs two campaigns.

SELECT
    i.advertiser_id AS campaign_id,
    i.advertiser_id,
    'Campaign ' || i.advertiser_id || ' · ' || a.industry AS campaign_name,
    2 AS season,
    MIN(i.impression_date) AS first_date,
    MAX(i.impression_date) AS last_date,
    COUNT(DISTINCT i.impression_date) AS days_live,
    (SELECT COUNT(*) > 0 FROM stg_bids b WHERE b.advertiser_id = i.advertiser_id) AS has_bid_logs
FROM stg_impressions i
JOIN dim_advertiser a ON i.advertiser_id = a.advertiser_id
GROUP BY i.advertiser_id, a.industry
ORDER BY i.advertiser_id;