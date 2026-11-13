-- Dimension table: dates.
-- Grain: one row per calendar day, from the first to the last impression date
-- (a day with no data still gets a row, so gaps are visible on charts).

WITH days AS (
    SELECT CAST(d AS DATE) AS date
    FROM RANGE(
        (SELECT MIN(impression_date) FROM stg_impressions),
        (SELECT MAX(impression_date) FROM stg_impressions) + INTERVAL 1 DAY,
        INTERVAL 1 DAY
    ) AS r(d)
)

SELECT
    date,
    DAYNAME(date) AS weekday,
    ISODOW(date) AS day_of_week,       -- 1 = Monday ... 7 = Sunday
    ISODOW(date) >= 6 AS is_weekend,
    STRFTIME(date, '%d %b %Y') AS label
FROM days
ORDER BY date;