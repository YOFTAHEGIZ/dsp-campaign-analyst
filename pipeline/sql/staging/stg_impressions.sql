-- Staging model: impressions (the DSP won the auction and the ad was shown).
-- Reads raw_imp: the hourly files in data/interim/imp/ that have arrived (see clean.py).
-- One row per impression. Rows that appear twice in the log (same bid_id, user
-- and timestamp) are kept once. Text 'null' becomes a real NULL.

SELECT
    -- A unique key for each impression. bid_id alone is not unique:
    -- the same bid_id can appear with a different user and time.
    MD5(CONCAT_WS('|', bid_id, ipinyou_id, timestamp)) AS imp_key,

    bid_id,

    -- Parse timestamp: YYYYMMDDHHMMSSmmm
    TRY_STRPTIME(SUBSTRING(timestamp, 1, 14), '%Y%m%d%H%M%S')
        + TRY_CAST(SUBSTRING(timestamp, 15, 3) AS INTEGER) * INTERVAL '1 millisecond'
        AS impression_datetime,

    -- Date and hour for daily and hourly reporting
    CAST(TRY_STRPTIME(SUBSTRING(timestamp, 1, 8), '%Y%m%d') AS DATE) AS impression_date,
    TRY_CAST(SUBSTRING(timestamp, 9, 2) AS INTEGER) AS hour,

    -- User and placement information
    NULLIF(ipinyou_id, 'null') AS ipinyou_id,
    user_agent,
    TRY_CAST(region AS INTEGER) AS region,
    TRY_CAST(city AS INTEGER) AS city,
    TRY_CAST(ad_exchange AS INTEGER) AS ad_exchange,
    NULLIF(domain, 'null') AS domain,
    ad_slot_id,
    creative_id,

    -- Ad slot information
    TRY_CAST(ad_slot_width AS INTEGER) AS ad_slot_width,
    TRY_CAST(ad_slot_height AS INTEGER) AS ad_slot_height,
    ad_slot_visibility,
    ad_slot_format,

    -- Prices (per 1,000 impressions, like a CPM)
    TRY_CAST(ad_slot_floor_price AS INTEGER) AS ad_slot_floor_price,
    TRY_CAST(bidding_price AS INTEGER) AS bidding_price,
    TRY_CAST(paying_price AS INTEGER) AS paying_price,

    TRY_CAST(advertiser_id AS INTEGER) AS advertiser_id,
    NULLIF(user_tags, 'null') AS user_tags,
    source_file

FROM raw_imp

-- Remove exact repeats of the same impression
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY bid_id, ipinyou_id, timestamp
    ORDER BY source_file
) = 1;