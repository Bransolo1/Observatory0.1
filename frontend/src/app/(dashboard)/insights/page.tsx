"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { ai } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { LensBreakdown } from "@/components/lens-breakdown";
import { LayoutDashboard, Sparkles, Loader2, ArrowRight } from "lucide-react";

const CAT_COLOR: Record<string, string> = {
  opportunity: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  risk: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  trend: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
};

export default function InsightsPage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["ai-insights", orgId],
    queryFn: () => ai.insights.get(orgId),
    enabled: !!orgId,
  });

  const { data: summary } = useQuery({
    queryKey: ["ai-summary", orgId],
    queryFn: () => ai.summary(orgId),
    enabled: !!orgId,
  });

  const generate = useMutation({
    mutationFn: () => ai.insights.generate(orgId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-insights", orgId] });
      qc.invalidateQueries({ queryKey: ["ai-summary", orgId] });
    },
  });

  if (isLoading) return <Skeleton className="h-64" />;

  const items = (data?.items || []) as Record<string, unknown>[];
  const hasKey = summary?.has_api_key ?? false;

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Insights</h1>
          <p className="text-muted-foreground">
            Cross-cutting findings synthesised from all your intelligence streams through 7 expert lenses
          </p>
        </div>
        <Button
          onClick={() => generate.mutate()}
          disabled={!hasKey || generate.isPending}
          size="sm"
        >
          {generate.isPending ? (
            <><Loader2 className="h-3 w-3 mr-1 animate-spin" /> Synthesising…</>
          ) : items.length > 0 ? (
            <><Sparkles className="h-3 w-3 mr-1" /> Regenerate</>
          ) : (
            <><Sparkles className="h-3 w-3 mr-1" /> Synthesise with Claude</>
          )}
        </Button>
      </div>

      {items.length === 0 ? (
        <Card>
          <EmptyState
            icon={LayoutDashboard}
            title="No insights yet"
            description={
              hasKey
                ? "Click 'Synthesise with Claude' to generate cross-cutting insights from your friction scenarios, competitor analyses, and experiment ideas. The more intelligence you've generated, the richer the insights."
                : "Add your Anthropic API key in Settings to synthesise insights with Claude."
            }
            action={hasKey ? undefined : { label: "Add API key", href: "/settings" }}
          />
        </Card>
      ) : (
        <>
          {data?.generated_at && (
            <p className="text-xs text-muted-foreground">
              Generated {new Date(data.generated_at).toLocaleString()}
            </p>
          )}
          <div className="space-y-3">
            {items.map((ins, i) => (
              <Card key={i}>
                <CardContent className="pt-5 pb-5">
                  <div className="flex items-start gap-2 mb-1 flex-wrap">
                    <Badge variant="outline" className={CAT_COLOR[ins.category as string] || ""}>
                      {ins.category as string}
                    </Badge>
                    {ins.confidence && (
                      <span className="text-[10px] text-muted-foreground">
                        {Math.round((ins.confidence as number) * 100)}% confidence
                      </span>
                    )}
                  </div>
                  <h3 className="font-semibold text-sm">{ins.title as string}</h3>
                  <p className="text-sm text-muted-foreground mt-1">{ins.summary as string}</p>
                  {ins.detail && (
                    <p className="text-xs text-muted-foreground mt-1">{ins.detail as string}</p>
                  )}
                  {(ins.related_areas as string[])?.length > 0 && (
                    <div className="flex gap-1 mt-2 flex-wrap">
                      {(ins.related_areas as string[]).map((a) => (
                        <Badge key={a} variant="secondary" className="text-[10px]">{a}</Badge>
                      ))}
                    </div>
                  )}
                  <LensBreakdown analysis={ins.lens_analysis as Record<string, string>} />
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="flex items-center justify-between p-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50">
            <p className="text-sm text-muted-foreground">
              Ready to act? See ranked experiment recommendations.
            </p>
            <Link href="/scores">
              <Button variant="outline" size="sm">
                Experiments <ArrowRight className="h-3 w-3 ml-1" />
              </Button>
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
