import os
from pathlib import Path

import duckdb
import psycopg
from dotenv import load_dotenv


# Find the project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Make relative file paths work from the project root
os.chdir(PROJECT_ROOT)

# Load environment variables
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.getenv("NEON_DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("NEON_DATABASE_URL was not found in .env")


def load_daily_campaign():

    # Create an in-memory DuckDB connection
    duckdb_conn = duckdb.connect(":memory:")

    # Load all four staging SQL models
    staging_folder = PROJECT_ROOT / "pipeline/sql/staging"

    for sql_file in sorted(staging_folder.glob("stg_*.sql")):

        sql = sql_file.read_text()

        table_name = sql_file.stem

        duckdb_conn.execute(
            f"CREATE OR REPLACE TEMP TABLE {table_name} AS {sql}"
        )

        print(f"Created staging table: {table_name}")

    # Run the daily campaign mart
    mart_sql = (
        PROJECT_ROOT / "pipeline/sql/marts/daily_campaign.sql"
    ).read_text()

    duckdb_conn.execute(
        f"CREATE OR REPLACE TEMP TABLE daily_campaign AS {mart_sql}"
    )

    # Retrieve daily campaign records
    rows = duckdb_conn.execute(
        "SELECT * FROM daily_campaign"
    ).fetchall()

    print(f"Prepared {len(rows)} daily campaign records.")

    # Connect to Neon and insert the records
    with psycopg.connect(DATABASE_URL) as neon_conn:

        with neon_conn.cursor() as cursor:

            cursor.executemany(
                """
                INSERT INTO daily_campaign (
                    advertiser_id,
                    report_date,
                    impressions,
                    clicks,
                    conversions,
                    total_cost
                )
                VALUES (%s, %s, %s, %s, %s, %s)

                ON CONFLICT (advertiser_id, report_date)
                DO UPDATE SET
                    impressions = EXCLUDED.impressions,
                    clicks = EXCLUDED.clicks,
                    conversions = EXCLUDED.conversions,
                    total_cost = EXCLUDED.total_cost;
                """,
                rows
            )

    print("Successfully loaded daily campaign data into Neon.")

    duckdb_conn.close()


if __name__ == "__main__":
    load_daily_campaign()