// One shared connection pool to Neon Postgres. NEON_DATABASE_URL lives in .env.local (local)
// and in the Vercel project's environment variables (production), never in the code.
import { Pool } from "pg";

declare global {
  var _pgPool: Pool | undefined;
}

const DATABASE_URL = process.env.NEON_DATABASE_URL ?? process.env.DATABASE_URL;

export const hasDatabase = Boolean(DATABASE_URL);

/** Neon's connection string ends in ?sslmode=require. The pg library prints a security
 *  warning for that setting, so we take sslmode out of the string and turn SSL on
 *  ourselves instead: the connection is encrypted and Neon's certificate is verified. */
function poolConfig(raw: string) {
  const url = new URL(raw);
  const mode = url.searchParams.get("sslmode");
  const useSsl = (mode !== null && mode !== "disable") || url.hostname.endsWith("neon.tech");
  url.searchParams.delete("sslmode");
  return { connectionString: url.toString(), ssl: useSsl ? { rejectUnauthorized: true } : undefined };
}

function pool(): Pool {
  if (!globalThis._pgPool) {
    globalThis._pgPool = new Pool({ ...poolConfig(DATABASE_URL!), max: 3 });
  }
  return globalThis._pgPool;
}

export async function query<T>(sql: string, params: unknown[] = []): Promise<T[]> {
  const res = await pool().query(sql, params);
  return res.rows as T[];
}