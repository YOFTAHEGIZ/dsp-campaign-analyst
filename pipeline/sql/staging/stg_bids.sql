-- Staging model for advertiser 1458 bids.

SELECT
    bid_id,

    -- Parse the original timestamp format:
    -- YYYYMMDDHHMMSSmmm
    STRPTIME(
        SUBSTRING(timestamp, 1, 14),
        '%Y%m%d%H%M%S'
    ) + TRY_CAST(
        SUBSTRING(timestamp, 15, 3) AS INTEGER
    ) * INTERVAL '1 millisecond' AS bid_datetime,

    -- Extract date and hour
    CAST(
        STRPTIME(SUBSTRING(timestamp, 1, 8), '%Y%m%d')
        AS DATE
    ) AS bid_date,

    TRY_CAST(SUBSTRING(timestamp, 9, 2) AS INTEGER) AS hour,

    -- User and advertising information
    ipinyou_id,
    ad_exchange,
    region,
    city,
    creative_id,

    -- Convert numeric columns
    TRY_CAST(ad_slot_width AS INTEGER) AS ad_slot_width,
    TRY_CAST(ad_slot_height AS INTEGER) AS ad_slot_height,
    TRY_CAST(ad_slot_floor_price AS INTEGER) AS ad_slot_floor_price,
    TRY_CAST(bidding_price AS INTEGER) AS bidding_price,

    advertiser_id

FROM read_parquet(
    'data/processed/parquet/advertiser_1458_bids_20130606.parquet'
);