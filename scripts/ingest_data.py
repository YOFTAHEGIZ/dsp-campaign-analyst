import duckdb

cols = ["bid_id", "timestamp", "log_type", "ipinyou_id", "user_agent", "ip",
                  "region", "city", "ad_exchange", "domain", "url", "anonymous_url_id",
                  "ad_slot_id", "ad_slot_width", "ad_slot_height", "ad_slot_visibility",
                  "ad_slot_format", "ad_slot_floor_price", "creative_id", "bidding_price",
                  "paying_price", "key_page_url", "advertiser_id", "user_tags"]
con = duckdb.connect("data/processed/ipinyou.duckdb")
con.execute(f"""
              CREATE OR REPLACE TABLE raw_imp AS
              SELECT * FROM read_csv('data/raw/imp.*.txt', delim='\\t', header=false,
                                     quote='', all_varchar=true, names={cols})
          """)
con.execute("""
              COPY (SELECT * FROM raw_imp WHERE advertiser_id = '1458')
              TO 'data/interim/imp_1458.parquet' (FORMAT parquet)
          """)
