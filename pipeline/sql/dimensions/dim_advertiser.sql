-- Dimension table: advertisers.
-- Grain: one row per advertiser found in the impressions.
-- Industries are from the iPinYou dataset paper (Zhang et al., 2014).

WITH industries AS (
    SELECT * FROM (VALUES
        (1458, 'Chinese vertical e-commerce'),
        (3358, 'Software'),
        (3386, 'International e-commerce'),
        (3427, 'Oil'),
        (3476, 'Tire')
    ) AS t(advertiser_id, industry)
)

SELECT
    a.advertiser_id,
    COALESCE(n.industry, 'unknown') AS industry,
    'Advertiser ' || a.advertiser_id || ' · ' || COALESCE(n.industry, 'unknown') AS advertiser_name
FROM (SELECT DISTINCT advertiser_id FROM stg_impressions) a
LEFT JOIN industries n ON a.advertiser_id = n.advertiser_id
ORDER BY a.advertiser_id;