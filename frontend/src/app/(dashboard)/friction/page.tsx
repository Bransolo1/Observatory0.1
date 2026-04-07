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
import { AlertTriangle, Sparkles, Loader2, ArrowRight } from "lucide-react";

const SEVERITY_COLOR: Record<string, string> = {
  critical: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  high: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
  medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-300",
  low: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
};

export default function FrictionPage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["ai-friction", orgId],
    queryFn: () => ai.frictionScenarios.get(orgId),
    enabled: !!orgId,
  });

  const { data: summary } = useQuery({
    queryKey: ["ai-summary", orgId],
    queryFn: () => ai.summary(orgId),
    enabled: !!orgId,
  });

  const generate = useMutation({
    mutationFn: () => ai.frictionScenarios.generate(orgId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-friction", orgId] });
      qc.invalidateQueries({ queryKey: ["ai-summary", orgId] });
    },
  });

  if (isLoading) return <Skeleton className="h-64" />;

  const items = data?.scenarios || data?.items || [];
  const hasKey = summary?.has_api_key ?? false;

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Friction Signals</h1>
          <p className="text-muted-foreground">
            Drop-offs, rage clicks, and funnel breaks hypothesised by Claude from your product context
          </p>
        </div>
        <Button
          onClick={() => generate.mutate()}
          disabled={!hasKey || generate.isPending}
          size="sm"
        >
          {generate.isPending ? (
            <><Loader2 className="h-3 w-3 mr-1 animate-spin" /> Generating…</>
          ) : items.length > 0 ? (
            <><Sparkles className="h-3 w-3 mr-1" /> Regenerate</>
          ) : (
            <><Sparkles className="h-3 w-3 mr-1" /> Generate with Claude</>
          )}
        </Button>
      </div>

      {items.length === 0 ? (
        <Card>
          <EmptyState
            icon={AlertTriangle}
            title="No friction scenarios yet"
            description={
              hasKey
                ? "Click 'Generate with Claude' to surface plausible friction signals based on your product areas. Claude analyses common patterns for your type of product and proposes where users are most likely to drop off."
                : "Add your Anthropic API key in Settings to generate friction scenarios with Claude."
            }
            action={
              hasKey
                ? undefined
                : { label: "Add API key", href: "/settings" }
            }
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
            {items.map((s: Record<string, string>, i: number) => (
              <Card key={i}>
                <CardContent className="pt-5 pb-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant="outline" className={SEVERITY_COLOR[s.severity] || ""}>
                          {s.severity}
                        </Badge>
                        <Badge variant="secondary" className="text-[10px]">
                          {s.signal_type}
                        </Badge>
                        {s.product_area && (
                          <span className="text-xs text-muted-foreground">{s.product_area}</span>
                        )}
                      </div>
                      <p className="font-medium text-sm">{s.description}</p>
                      {s.hypothesis && (
                        <p className="text-xs text-muted-foreground mt-1">
                          <span className="font-medium">Hypothesis:</span> {s.hypothesis}
                        </p>
                      )}
                      {s.funnel_step && (
                        <p className="text-xs text-muted-foreground">
                          <span className="font-medium">Funnel step:</span> {s.funnel_step}
                        </p>
                      )}
                      {s.investigation_next_step && (
                        <p className="text-xs text-muted-foreground mt-1.5 p-2 bg-zinc-50 dark:bg-zinc-900 rounded">
                          <span className="font-medium">Next step:</span> {s.investigation_next_step}
                        </p>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="flex items-center justify-between p-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50">
            <p className="text-sm text-muted-foreground">
              Have scenarios? Commission research to validate them.
            </p>
            <Link href="/research">
              <Button variant="outline" size="sm">
                Research pipeline <ArrowRight className="h-3 w-3 ml-1" />
              </Button>
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
