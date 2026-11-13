-- Daily auction mart (auction stats).
-- Grain: one row per advertiser, day, ad exchange and floor price band.
--
-- bids come from the bid summary (all advertisers); wins are the impressions
-- (an impression is a won auction). From these sums the dashboard computes:
--   win rate        = wins / bids
--   average bid     = sum_bid_price / bids
--   average paid    = sum_paying_price / wins
--   paid / bid      = sum_paying_price / sum_bid_price_won   (second-price discount)
--   floor set price = floor_set_price / wins
-- Prices here are the raw log values (per 1,000 impressions).

WITH bids AS (
    SELECT
        advertiser_id,
        bid_date AS report_date,
        ad_exchange,
        floor_band,
        SUM(bids) AS bids,
        SUM(sum_bidding_price) AS sum_bid_price
    FROM stg_bid_summary
    GROUP BY advertiser_id, bid_date, ad_exchange, floor_band
),

wins AS (
    SELECT
        advertiser_id,
        impression_date AS report_date,
        ad_exchange,
        floor_band,
        COUNT(*) AS wins,
        SUM(bidding_price) AS sum_bid_price_won,
        SUM(paying_price) AS sum_paying_price,
        SUM(floor_price) AS sum_floor_price,
        -- The floor set the price: we paid exactly the floor (and the floor was above 0)
        COUNT(*) FILTER (WHERE paying_price = floor_price AND floor_price > 0) AS floor_set_price,
        -- Rule-breaking prices, kept and counted (see docs/data_decisions.md)
        COUNT(*) FILTER (WHERE paying_price > bidding_price) AS paid_above_bid,
        COUNT(*) FILTER (WHERE paying_price < floor_price) AS paid_below_floor
    FROM fact_impressions
    GROUP BY advertiser_id, impression_date, ad_exchange, floor_band
)

SELECT
    COALESCE(w.advertiser_id, b.advertiser_id) AS advertiser_id,
    COALESCE(w.report_date, b.report_date) AS report_date,
    COALESCE(w.ad_exchange, b.ad_exchange) AS ad_exchange,
    COALESCE(w.floor_band, b.floor_band) AS floor_band,
    COALESCE(b.bids, 0) AS bids,
    COALESCE(w.wins, 0) AS wins,
    COALESCE(b.sum_bid_price, 0) AS sum_bid_price,
    COALESCE(w.sum_bid_price_won, 0) AS sum_bid_price_won,
    COALESCE(w.sum_paying_price, 0) AS sum_paying_price,
    COALESCE(w.sum_floor_price, 0) AS sum_floor_price,
    COALESCE(w.floor_set_price, 0) AS floor_set_price,
    COALESCE(w.paid_above_bid, 0) AS paid_above_bid,
    COALESCE(w.paid_below_floor, 0) AS paid_below_floor
FROM wins w
FULL JOIN bids b
    ON w.advertiser_id = b.advertiser_id
    AND w.report_date = b.report_date
    AND w.ad_exchange IS NOT DISTINCT FROM b.ad_exchange
    AND w.floor_band = b.floor_band
ORDER BY 1, 2, 3, 4;