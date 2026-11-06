
import { pool } from "@/lib/db";

export const instant = false;

type CampaignDay = {
  report_date: string;
  impressions: string;
  clicks: string;
  conversions: string;
  total_cost: string;
};

function formatNumber(value: string | number) {
  return new Intl.NumberFormat("en-US").format(Number(value));
}

export default async function Home() {
  const [summaryResult, dailyResult] = await Promise.all([
    pool.query(
      `SELECT
        COALESCE(SUM(impressions), 0) AS impressions,
        COALESCE(SUM(clicks), 0) AS clicks,
        COALESCE(SUM(conversions), 0) AS conversions,
        COALESCE(SUM(total_cost), 0) AS total_cost
       FROM daily_campaign
       WHERE advertiser_id = $1`,
      ["1458"]
    ),

    pool.query(
      `SELECT
        TO_CHAR(report_date, 'YYYY-MM-DD') AS report_date,
        impressions::text,
        clicks::text,
        conversions::text,
        total_cost::text
       FROM daily_campaign
       WHERE advertiser_id = $1
       ORDER BY report_date`,
      ["1458"]
    ),
  ]);

  const summary = summaryResult.rows[0];
  const dailyRows = dailyResult.rows as CampaignDay[];

  const metrics = [
    { label: "Impressions", value: summary.impressions },
    { label: "Clicks", value: summary.clicks },
    { label: "Conversions", value: summary.conversions },
    { label: "Total Cost", value: summary.total_cost },
  ];

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-12 text-white">
      <div className="mx-auto max-w-6xl">
        <div className="mb-10">
          <p className="text-sm font-medium text-blue-400">
            AI CAMPAIGN ANALYST
          </p>
          <h1 className="mt-2 text-3xl font-bold">
            Campaign Dashboard
          </h1>
          <p className="mt-2 text-slate-400">
            Advertiser 1458 · Live data from Neon PostgreSQL
          </p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {metrics.map((metric) => (
            <div
              key={metric.label}
              className="rounded-xl border border-slate-800 bg-slate-900 p-6"
            >
              <p className="text-sm text-slate-400">
                {metric.label}
              </p>
              <p className="mt-3 text-2xl font-bold">
                {formatNumber(metric.value)}
              </p>
            </div>
          ))}
        </div>

        <section className="mt-10 rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="mb-5 text-xl font-semibold">
            Daily Campaign Performance
          </h2>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-700 text-slate-400">
                <tr>
                  <th className="py-3 pr-4">Date</th>
                  <th className="py-3 pr-4">Impressions</th>
                  <th className="py-3 pr-4">Clicks</th>
                  <th className="py-3 pr-4">Conversions</th>
                  <th className="py-3">Total Cost</th>
                </tr>
              </thead>

              <tbody>
                {dailyRows.map((day) => (
                  <tr
                    key={day.report_date}
                    className="border-b border-slate-800"
                  >
                    <td className="py-4 pr-4">{day.report_date}</td>
                    <td className="py-4 pr-4">
                      {formatNumber(day.impressions)}
                    </td>
                    <td className="py-4 pr-4">
                      {formatNumber(day.clicks)}
                    </td>
                    <td className="py-4 pr-4">
                      {formatNumber(day.conversions)}
                    </td>
                    <td className="py-4">
                      {formatNumber(day.total_cost)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
