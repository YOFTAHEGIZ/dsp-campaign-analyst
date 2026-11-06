-- Staging model for advertiser 1458 impressions.
-- Read the already processed Parquet file.

SELECT
    bid_id,

    -- Convert Unix timestamp into a timestamp
    datetime AS impression_datetime,

    -- Keep the date and hour for daily reporting
    CAST(datetime AS DATE) AS impression_date,
    hour,

    -- User and advertising information
    ipinyou_id,
    ad_exchange,
    region,
    city,
    creative_id,

    -- Ad slot information
    ad_slot_width,
    ad_slot_height,
    ad_slot_visibility,
    ad_slot_format,

    -- Price information
    ad_slot_floor_price,
    bidding_price,
    paying_price,

    -- Advertiser identification
    advertiser_id

FROM read_parquet(
    'data/processed/parquet/advertiser_1458_impressions_20130606.parquet'
);