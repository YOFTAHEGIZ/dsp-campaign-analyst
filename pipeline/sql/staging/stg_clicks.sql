-- Staging model: clicks.
-- Reads raw_clk: the hourly files in data/interim/clk/ that have arrived (see clean.py).
-- A row that appears twice in the log (exactly the same) is kept once.
-- Linking each click to its impression happens later, in the marts.

SELECT DISTINCT
    bid_id,

    -- Parse timestamp: YYYYMMDDHHMMSSmmm
    TRY_STRPTIME(SUBSTRING(timestamp, 1, 14), '%Y%m%d%H%M%S')
        + TRY_CAST(SUBSTRING(timestamp, 15, 3) AS INTEGER) * INTERVAL '1 millisecond'
        AS click_datetime,

    CAST(TRY_STRPTIME(SUBSTRING(timestamp, 1, 8), '%Y%m%d') AS DATE) AS click_date,
    TRY_CAST(SUBSTRING(timestamp, 9, 2) AS INTEGER) AS hour,

    NULLIF(ipinyou_id, 'null') AS ipinyou_id,
    TRY_CAST(region AS INTEGER) AS region,
    TRY_CAST(city AS INTEGER) AS city,
    TRY_CAST(ad_exchange AS INTEGER) AS ad_exchange,
    ad_slot_id,
    creative_id,

    TRY_CAST(ad_slot_width AS INTEGER) AS ad_slot_width,
    TRY_CAST(ad_slot_height AS INTEGER) AS ad_slot_height,
    TRY_CAST(ad_slot_floor_price AS INTEGER) AS ad_slot_floor_price,
    TRY_CAST(bidding_price AS INTEGER) AS bidding_price,
    TRY_CAST(paying_price AS INTEGER) AS paying_price,

    TRY_CAST(advertiser_id AS INTEGER) AS advertiser_id

FROM raw_clk;