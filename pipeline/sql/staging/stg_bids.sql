-- Staging model: bids (every auction the DSP bid in, won or lost).
-- Reads raw_bid: the hourly files in data/interim/bid/ that have arrived (see clean.py).
-- Only the columns the auction analysis needs, to keep this fast on a big log.

SELECT
    bid_id,

    -- Parse timestamp: YYYYMMDDHHMMSSmmm
    TRY_STRPTIME(SUBSTRING(timestamp, 1, 14), '%Y%m%d%H%M%S')
        + TRY_CAST(SUBSTRING(timestamp, 15, 3) AS INTEGER) * INTERVAL '1 millisecond'
        AS bid_datetime,

    CAST(TRY_STRPTIME(SUBSTRING(timestamp, 1, 8), '%Y%m%d') AS DATE) AS bid_date,
    TRY_CAST(SUBSTRING(timestamp, 9, 2) AS INTEGER) AS hour,

    NULLIF(ipinyou_id, 'null') AS ipinyou_id,
    TRY_CAST(region AS INTEGER) AS region,
    TRY_CAST(city AS INTEGER) AS city,
    TRY_CAST(ad_exchange AS INTEGER) AS ad_exchange,
    creative_id,

    TRY_CAST(ad_slot_width AS INTEGER) AS ad_slot_width,
    TRY_CAST(ad_slot_height AS INTEGER) AS ad_slot_height,
    TRY_CAST(ad_slot_floor_price AS INTEGER) AS ad_slot_floor_price,
    TRY_CAST(bidding_price AS INTEGER) AS bidding_price,

    TRY_CAST(advertiser_id AS INTEGER) AS advertiser_id

FROM raw_bid;