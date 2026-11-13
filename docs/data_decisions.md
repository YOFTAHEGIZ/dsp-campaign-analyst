# Data decisions

This file explains the choices I made about the data: which columns I use, which I drop,
and how I clean the raw logs. Most of these choices come from my Task 2 analysis.

## How much data

iPinYou Season 2: 7 days (6–12 June 2013), 5 advertisers.

| What | Rows |
| --- | --- |
| Impressions (ads shown) | 12,237,081 |
| Clicks | 9,978 |
| Conversions (purchases) | 418 |
| Bids (advertiser 1458 only, to save disk) | 14,701,496 |

Advertisers: 1458, 3358, 3386, 3427, 3476.

## How the data moves

```
raw .bz2 files  →  Parquet files  →  cleaned  →  facts and dimensions  →  Neon  →  dashboard
   ingest.py         (all text)       clean.py         model.py             load.py
```

The Parquet files keep every column. So if I need a dropped column later,
I can add it back without converting the raw files again.

## Columns I keep

These are useful for filtering and grouping on the dashboard.

| Column | Why |
| --- | --- |
| `timestamp` | Becomes date and hour: daily and hourly reports |
| `advertiser_id` | Which advertiser (also used as the campaign) |
| `ad_exchange` | Where the ad was bought (only 3 values) |
| `region`, `city` | Where the user was |
| `ad_slot_width`, `ad_slot_height` | The ad size |
| `ad_slot_visibility`, `ad_slot_format` | Above or below the fold, fixed or pop-up |
| `ad_slot_floor_price` | The minimum price of the auction |
| `bidding_price` | What we offered |
| `paying_price` | What we paid |
| `creative_id` | Which ad image was shown |
| `user_tags` | The user's interest groups |
| `bid_id`, `ipinyou_id` | Not shown on the dashboard, but needed to match clicks to impressions |

## Columns I drop

| Column | Why |
| --- | --- |
| `log_type` | Same value in the whole file (1 = impression, 2 = click, 3 = conversion) |
| `url`, `domain`, `ad_slot_id` | Scrambled codes nobody can read, almost all different |
| `anonymous_url_id` | Always empty |
| `ip` | Close to personal data, and not needed for reporting |
| `key_page_url` | Only means something for conversions |

## Columns I change or add

| New column | Made from | Why |
| --- | --- | --- |
| `device`, `os`, `browser` | `user_agent` | The user agent is a long technical text. These 3 simple fields can be filtered on (in Task 2, mobile and desktop behaved differently). |
| `cost` | `paying_price` ÷ 1000 | Prices are per 1,000 ads, so one ad costs the price divided by 1,000 |

## How I clean the data

1. **`null` means empty.** The logs write a missing value as the word `null`.
   I turn it into a real empty value.

2. **Uneven rows.** One conversion row had 23 columns instead of 24 (the last one was missing).
   I keep it and leave the missing column empty.

3. **Duplicates.** If the same impression appears twice, I keep one (6 removed).

4. **`bid_id` is not unique.** The same `bid_id` can appear for different users.
   So I match a click to its impression using **bid + user + time**, not bid alone.

5. **Matching clicks to impressions.** For each click I look for, in this order:

   | Rule | How it matches | Clicks | Conversions |
   | --- | --- | --- | --- |
   | 1 | same bid and same user, impression before the click | 8,047 | 299 |
   | 2 | same bid, user different or missing | 1,172 | 106 |
   | 3 | same bid, closest time (log clocks differ a little) | 655 | 0 |
   | 4 | no impression found: kept, counted on its own date | 104 | 13 |

6. **Clicks count on the day the ad was shown.** A click at 00:05 on an ad shown at 23:58
   counts on the earlier day. That keeps each day's click rate correct.

7. **Post-click or post-view.** A conversion is *post-click* if the ad was clicked first,
   *post-view* if the ad was only seen.

8. **Strange prices are kept but reported.** In this kind of auction you should never pay more
   than your bid, or less than the floor. But 191,091 ads paid more than the bid and
   64,113 paid less than the floor. I keep them (they are real spend) and the pipeline
   reports them every time it runs.

9. **Bids for one advertiser on my laptop.** The bid files are very big, so on my laptop
   I keep bids only for 1458 (`BID_ADVERTISER_IDS=1458`). The code's default is all advertisers.
   Advertisers 3386 and 3427 have no conversions in the data.

10. **Rates are total ÷ total.** Click rate = all clicks ÷ all impressions.
    I never average daily rates, because that gives a small day the same weight as a big one.

## Automatic checks

Every time the pipeline runs:

- `clean.py` runs 17 checks (saved in `reports/pipeline_data_quality.csv`).
  If a serious one fails, nothing is sent to Neon.
- `model.py` checks that the daily totals match the fact tables.
- `pytest pipeline/tests` tests each cleaning rule on small made-up rows.

The full statistics for every column are in `reports/column_profile.csv`
(made by `python pipeline/src/pipeline/profile.py`).