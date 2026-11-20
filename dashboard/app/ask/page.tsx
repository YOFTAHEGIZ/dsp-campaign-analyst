// Tab 4: ask the data. A question goes to an AI agent that may only read the dashboard tables
// (read-only role, SELECT only, row and time limits). Its answer is fact-checked by a second AI
// against the query results and shown with the SQL. See lib/ai.ts.
import Shell, { NoDatabase } from "@/components/Shell";
import AskBox from "@/components/AskBox";
import { hasDatabase } from "@/lib/db";
import { aiReady, LIMITS } from "@/lib/ai";
import { getAdvertisers, getDays, getLastLoad, getStatus, parseFilters } from "@/lib/data";

export const instant = false;

type Search = { advertiser?: string; from?: string; to?: string };

export default async function Ask({ searchParams }: { searchParams: Promise<Search> }) {
  if (!hasDatabase) return <NoDatabase />;
  const [sp, advertisers, days, lastLoad, status] = await Promise.all([
    searchParams, getAdvertisers(), getDays(), getLastLoad(), getStatus()]);
  const filters = parseFilters(sp, advertisers, days);
  return (
    <Shell tab="ask" advertisers={advertisers} days={days} filters={filters} lastLoad={lastLoad} status={status}>
      <p className="note">
        Ask in plain English. An AI writes SQL, runs it with a read-only account on the dashboard tables
        (SELECT only, at most {LIMITS.rows} rows, {LIMITS.timeoutMs / 1000} seconds), and answers from the results only.
        A second AI checks every number before you see it. The filters above don&apos;t apply here: name the
        advertiser or dates in your question.
      </p>
      {aiReady ? <AskBox /> : (
        <p className="warn">Not set up yet: add AI_DATABASE_URL, GOOGLE_GENERATIVE_AI_API_KEY (or GROQ_API_KEY) and
          COHERE_API_KEY to the environment variables.</p>
      )}
    </Shell>
  );
}