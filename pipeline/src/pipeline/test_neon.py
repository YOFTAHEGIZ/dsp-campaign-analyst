import os
import psycopg
from dotenv import load_dotenv

# Load environment variables from the project root
load_dotenv()

# Get the Neon connection string
DATABASE_URL = os.getenv("NEON_DATABASE_URL")

# Check that the connection string exists
if not DATABASE_URL:
    raise ValueError("NEON_DATABASE_URL was not found in .env")

# Connect to Neon and test the connection
with psycopg.connect(DATABASE_URL) as conn:

    with conn.cursor() as cur:

        # Ask PostgreSQL to return its version
        cur.execute("SELECT version();")

        result = cur.fetchone()

        print("Successfully connected to Neon!")
        print(result[0])