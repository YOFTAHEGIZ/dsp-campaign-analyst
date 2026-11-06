import "server-only";
import { Pool } from "pg";

const connectionString = process.env.NEON_DATABASE_URL;

if (!connectionString) {
  throw new Error("NEON_DATABASE_URL is not configured");
}

export const pool = new Pool({
  connectionString,
  max: 5,
});