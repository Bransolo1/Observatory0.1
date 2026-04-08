"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { costs, type CostSummary } from "@/lib/api";

function ProgressBar({ value, max, color = "bg-black" }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const danger = pct > 80;
  return (
    <div className="w-full bg-gray-100 rounded-full h-3">
      <div
        className={`h-3 rounded-full transition-all ${danger ? "bg-red-500" : color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function ServiceCard({
  name,
  daily,
  dailyLimit,
  monthly,
  monthlyLimit,
  calls,
}: {
  name: string;
  daily: number;
  dailyLimit: number;
  monthly: number;
  monthlyLimit: number;
  calls: number;
}) {
  return (
    <div className="border rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold capitalize">{name}</h3>
        <span className="text-xs text-muted-foreground">{calls} calls today</span>
      </div>
      <div className="space-y-1">
        <div className="flex justify-between text-sm">
          <span>Daily</span>
          <span className={daily > dailyLimit * 0.8 ? "text-red-600 font-medium" : ""}>
            {"\u00A3"}{daily.toFixed(3)} / {"\u00A3"}{dailyLimit.toFixed(2)}
          </span>
        </div>
        <ProgressBar value={daily} max={dailyLimit} />
      </div>
      <div className="space-y-1">
        <div className="flex justify-between text-sm">
          <span>Monthly</span>
          <span className={monthly > monthlyLimit * 0.8 ? "text-red-600 font-medium" : ""}>
            {"\u00A3"}{monthly.toFixed(3)} / {"\u00A3"}{monthlyLimit.toFixed(2)}
          </span>
        </div>
        <ProgressBar value={monthly} max={monthlyLimit} color="bg-gray-700" />
      </div>
    </div>
  );
}

export default function CostsPage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id;
  const [data, setData] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async () => {
    if (!orgId) return;
    try {
      setLoading(true);
      const summary = await costs.summary(orgId);
      setData(summary);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load costs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // Auto-refresh every 30s
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  if (loading && !data) {
    return (
      <div className="p-8">
        <h1 className="text-3xl font-bold italic mb-2">Cost Controls</h1>
        <p className="text-muted-foreground">Loading spend data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <h1 className="text-3xl font-bold italic mb-2">Cost Controls</h1>
        <p className="text-red-600">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  const services = ["anthropic", "perplexity", "firecrawl", "serpapi"];

  return (
    <div className="p-8 max-w-5xl space-y-8">
      <div>
        <h1 className="text-3xl font-bold italic">Cost Controls</h1>
        <p className="text-muted-foreground mt-1">
          Real-time API spend tracking with hard budget limits. All costs in GBP.
        </p>
      </div>

      {/* Overall budget summary */}
      <div className="grid grid-cols-2 gap-6">
        <div className="border rounded-lg p-5 space-y-3">
          <h2 className="font-semibold text-lg">Today</h2>
          <div className="text-3xl font-bold">
            {"\u00A3"}{data.daily.total_spend.toFixed(3)}
            <span className="text-lg font-normal text-muted-foreground">
              {" "}/ {"\u00A3"}{data.daily.total_limit.toFixed(2)}
            </span>
          </div>
          <ProgressBar value={data.daily.total_spend} max={data.daily.total_limit} />
          <p className="text-sm text-muted-foreground">
            {"\u00A3"}{data.daily.remaining.toFixed(3)} remaining today
          </p>
        </div>
        <div className="border rounded-lg p-5 space-y-3">
          <h2 className="font-semibold text-lg">This Month</h2>
          <div className="text-3xl font-bold">
            {"\u00A3"}{data.monthly.total_spend.toFixed(3)}
            <span className="text-lg font-normal text-muted-foreground">
              {" "}/ {"\u00A3"}{data.monthly.total_limit.toFixed(2)}
            </span>
          </div>
          <ProgressBar value={data.monthly.total_spend} max={data.monthly.total_limit} color="bg-gray-700" />
          <p className="text-sm text-muted-foreground">
            {"\u00A3"}{data.monthly.remaining.toFixed(3)} remaining this month
          </p>
        </div>
      </div>

      {/* Per-service breakdown */}
      <div>
        <h2 className="font-semibold text-lg mb-3">Per-Service Breakdown</h2>
        <div className="grid grid-cols-2 gap-4">
          {services.map((svc) => (
            <ServiceCard
              key={svc}
              name={svc}
              daily={data.daily.by_service[svc]?.spend ?? 0}
              dailyLimit={data.limits[`daily_${svc}`] ?? 5}
              monthly={data.monthly.by_service[svc]?.spend ?? 0}
              monthlyLimit={data.limits[`monthly_${svc}`] ?? 20}
              calls={data.daily.by_service[svc]?.calls ?? 0}
            />
          ))}
        </div>
      </div>

      {/* Safety limits */}
      <div>
        <h2 className="font-semibold text-lg mb-3">Safety Limits</h2>
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "Max tokens/request", value: data.limits.max_tokens_per_request },
            { label: "Max chat iterations", value: data.limits.max_chat_iterations },
            { label: "Max specialist iterations", value: data.limits.max_specialist_iterations },
            { label: "Max crawl pages", value: data.limits.max_crawl_pages },
            { label: "Max specialists/turn", value: data.limits.max_specialist_consults_per_turn },
          ].map((item) => (
            <div key={item.label} className="border rounded-lg p-3 text-center">
              <p className="text-2xl font-bold">{item.value}</p>
              <p className="text-xs text-muted-foreground">{item.label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Recent API calls */}
      <div>
        <h2 className="font-semibold text-lg mb-3">Recent API Calls</h2>
        {data.recent_calls.length === 0 ? (
          <p className="text-muted-foreground text-sm">No API calls recorded yet.</p>
        ) : (
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr>
                  <th className="text-left p-2 font-medium">Service</th>
                  <th className="text-left p-2 font-medium">Endpoint</th>
                  <th className="text-left p-2 font-medium">Model</th>
                  <th className="text-right p-2 font-medium">Tokens (in/out)</th>
                  <th className="text-right p-2 font-medium">Cost</th>
                  <th className="text-right p-2 font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_calls.map((call, i) => (
                  <tr key={i} className="border-t">
                    <td className="p-2 capitalize">{call.service}</td>
                    <td className="p-2 font-mono text-xs">{call.endpoint}</td>
                    <td className="p-2 text-xs">{call.model || "-"}</td>
                    <td className="p-2 text-right font-mono text-xs">
                      {call.input_tokens > 0 ? `${call.input_tokens}/${call.output_tokens}` : "-"}
                    </td>
                    <td className="p-2 text-right font-medium">
                      {"\u00A3"}{call.estimated_cost_gbp.toFixed(4)}
                    </td>
                    <td className="p-2 text-right text-xs text-muted-foreground">
                      {new Date(call.created_at).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Explanation */}
      <div className="border-l-4 border-amber-400 bg-amber-50 p-4 rounded-r-lg">
        <h3 className="font-semibold text-amber-900">How cost controls work</h3>
        <ul className="text-sm text-amber-800 mt-2 space-y-1 list-disc list-inside">
          <li>Every API call is checked against daily and monthly budgets <strong>before</strong> it runs</li>
          <li>If a budget is exhausted, the request is rejected with a 429 error</li>
          <li>The CCO chat is capped at {data.limits.max_chat_iterations} iterations and {data.limits.max_specialist_consults_per_turn} specialist consultations per turn</li>
          <li>Crawl operations are capped at {data.limits.max_crawl_pages} pages maximum</li>
          <li>HackerNews and Reddit are free and have no cost limits</li>
          <li>All costs are estimates based on published API pricing</li>
        </ul>
      </div>
    </div>
  );
}
