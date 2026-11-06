import nextEnv from "@next/env";
import pg from "pg";

const { loadEnvConfig } = nextEnv;

loadEnvConfig(process.cwd());

const { Pool } = pg;
const connectionString = process.env.NEON_DATABASE_URL;

if (!connectionString) {
  throw new Error("NEON_DATABASE_URL is not configured");
}

const pool = new Pool({
  connectionString,
  max: 1,
});

try {
  const result = await pool.query(`
    SELECT
      COUNT(*) AS records,
      COALESCE(SUM(impressions), 0) AS impressions,
      COALESCE(SUM(clicks), 0) AS clicks,
      COALESCE(SUM(conversions), 0) AS conversions,
      COALESCE(SUM(total_cost), 0) AS total_cost
    FROM daily_campaign
    WHERE advertiser_id = '1458';
  `);

  console.log("Successfully connected to Neon!");
  console.log("Campaign summary:", result.rows[0]);
} catch (error) {
  console.error("Database connection failed:", error.message);
  process.exitCode = 1;
} finally {
  await pool.end();
}