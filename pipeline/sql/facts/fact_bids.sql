-- Fact table: bids.
-- Grain: one row per bid (won or lost).
-- Built as a VIEW over the Parquet files: millions of rows are not copied.
-- Only the advertisers in BID_ADVERTISER_IDS are in the bid files.

SELECT
    bid_id,
    advertiser_id,
    advertiser_id AS campaign_id,
    bid_datetime,
    bid_date,
    hour,
    ad_exchange,
    region,
    city,
    ad_slot_width,
    ad_slot_height,
    ad_slot_floor_price AS floor_price,
    bidding_price
FROM stg_bids;