-- Intermediate model: device, operating system and browser for each user agent.
-- One row per distinct user agent string. Each string is parsed once here,
-- instead of once per impression (12 million rows share a few thousand strings).
-- From Task 2 (notebook 05): mobile and desktop behave very differently.

WITH agents AS (
    SELECT DISTINCT
        user_agent,
        LOWER(COALESCE(user_agent, '')) AS ua
    FROM stg_impressions
)

SELECT
    user_agent,

    CASE
        WHEN ua = '' THEN 'unknown'
        WHEN REGEXP_MATCHES(ua, 'ipad|tablet') THEN 'tablet'
        WHEN REGEXP_MATCHES(ua, 'mobile|android|iphone|ipod|windows phone|symbian|blackberry|nokia|ucweb|opera mini|midp') THEN 'mobile'
        ELSE 'desktop'
    END AS device,

    CASE
        WHEN ua = '' THEN 'unknown'
        WHEN REGEXP_MATCHES(ua, 'iphone|ipad|ipod') THEN 'iOS'
        WHEN REGEXP_MATCHES(ua, 'android') THEN 'Android'
        WHEN REGEXP_MATCHES(ua, 'windows nt 5\.1|windows xp') THEN 'Windows XP'
        WHEN REGEXP_MATCHES(ua, 'windows nt 6\.1') THEN 'Windows 7'
        WHEN REGEXP_MATCHES(ua, 'windows nt 6\.[23]') THEN 'Windows 8'
        WHEN REGEXP_MATCHES(ua, 'windows') THEN 'Windows (other)'
        WHEN REGEXP_MATCHES(ua, 'mac os|macintosh') THEN 'macOS'
        WHEN REGEXP_MATCHES(ua, 'linux') THEN 'Linux'
        ELSE 'other'
    END AS os,

    CASE
        WHEN ua = '' THEN 'unknown'
        WHEN REGEXP_MATCHES(ua, 'metasr|sogou') THEN 'Sogou'
        WHEN REGEXP_MATCHES(ua, '360se|360ee|360browser') THEN '360'
        WHEN REGEXP_MATCHES(ua, 'maxthon') THEN 'Maxthon'
        WHEN REGEXP_MATCHES(ua, 'theworld') THEN 'TheWorld'
        WHEN REGEXP_MATCHES(ua, 'qqbrowser|tencenttraveler') THEN 'QQ'
        WHEN REGEXP_MATCHES(ua, 'ucbrowser|ucweb') THEN 'UC'
        WHEN REGEXP_MATCHES(ua, 'opera|opr/') THEN 'Opera'
        WHEN REGEXP_MATCHES(ua, 'chrome|crios') THEN 'Chrome'
        WHEN REGEXP_MATCHES(ua, 'firefox') THEN 'Firefox'
        WHEN REGEXP_MATCHES(ua, 'msie|trident') THEN 'IE'
        WHEN REGEXP_MATCHES(ua, 'safari') THEN 'Safari'
        ELSE 'other'
    END AS browser

FROM agents;