-- Fact table: clicks.
-- Grain: one row per click event.
-- report_date is the impression's date (the day the ad was shown). For the few
-- clicks with no impression found (link_rule 4) it is the click's own date.

SELECT
    click_id,
    imp_key,
    bid_id,
    ipinyou_id AS user_id,
    advertiser_id,
    advertiser_id AS campaign_id,
    click_datetime,
    click_date,
    impression_datetime,
    impression_date,
    COALESCE(impression_date, click_date) AS report_date,
    link_rule
FROM int_clicks_linked;