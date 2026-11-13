-- Fact table: conversions.
-- Grain: one row per conversion event.
-- report_date is the impression's date; conversion_type is post-click, post-view
-- or 'no impression'.

SELECT
    conversion_id,
    imp_key,
    bid_id,
    ipinyou_id AS user_id,
    advertiser_id,
    advertiser_id AS campaign_id,
    conversion_datetime,
    conversion_date,
    impression_datetime,
    impression_date,
    COALESCE(impression_date, conversion_date) AS report_date,
    conversion_type,
    link_rule
FROM int_conversions_linked;