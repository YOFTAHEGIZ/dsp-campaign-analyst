-- Staging model: bid counts for ALL advertisers (made by ingest.py while reading the bid logs).
-- Grain: one row per advertiser, date, hour, ad exchange and floor price.
-- Used for win rate and average bid, even for advertisers whose full bid rows are not kept.

SELECT
    TRY_CAST(advertiser_id AS INTEGER) AS advertiser_id,
    CAST(TRY_STRPTIME(bid_date, '%Y%m%d') AS DATE) AS bid_date,
    TRY_CAST(hour AS INTEGER) AS hour,
    TRY_CAST(ad_exchange AS INTEGER) AS ad_exchange,
    TRY_CAST(floor_price AS INTEGER) AS floor_price,

    -- Floor price groups (same bands as fact_impressions)
    CASE
        WHEN TRY_CAST(floor_price AS INTEGER) IS NULL THEN 'unknown'
        WHEN TRY_CAST(floor_price AS INTEGER) = 0 THEN '0'
        WHEN TRY_CAST(floor_price AS INTEGER) <= 10 THEN '1-10'
        WHEN TRY_CAST(floor_price AS INTEGER) <= 50 THEN '11-50'
        WHEN TRY_CAST(floor_price AS INTEGER) <= 100 THEN '51-100'
        WHEN TRY_CAST(floor_price AS INTEGER) <= 200 THEN '101-200'
        ELSE '200+'
    END AS floor_band,

    bids,
    sum_bidding_price
FROM raw_bid_summary;