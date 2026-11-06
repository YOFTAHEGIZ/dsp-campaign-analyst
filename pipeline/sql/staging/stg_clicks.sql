-- Staging model for advertiser 1458 clicks.

SELECT
    bid_id,

    -- Parse timestamp: YYYYMMDDHHMMSSmmm
    STRPTIME(
        SUBSTRING(timestamp, 1, 14),
        '%Y%m%d%H%M%S'
    ) + TRY_CAST(
        SUBSTRING(timestamp, 15, 3) AS INTEGER
    ) * INTERVAL '1 millisecond' AS click_datetime,

    -- Extract date and hour
    CAST(
        STRPTIME(SUBSTRING(timestamp, 1, 8), '%Y%m%d')
        AS DATE
    ) AS click_date,

    TRY_CAST(SUBSTRING(timestamp, 9, 2) AS INTEGER) AS hour,

    -- User and advertising information
    ipinyou_id,
    ad_exchange,
    region,
    city,
    creative_id,

    -- Ad slot information
    TRY_CAST(ad_slot_width AS INTEGER) AS ad_slot_width,
    TRY_CAST(ad_slot_height AS INTEGER) AS ad_slot_height,
    TRY_CAST(ad_slot_floor_price AS INTEGER) AS ad_slot_floor_price,

    -- Price information
    TRY_CAST(bidding_price AS INTEGER) AS bidding_price,
    TRY_CAST(paying_price AS INTEGER) AS paying_price,

    advertiser_id

FROM read_parquet(
    'data/processed/parquet/advertiser_1458_clicks_20130606.parquet'
);