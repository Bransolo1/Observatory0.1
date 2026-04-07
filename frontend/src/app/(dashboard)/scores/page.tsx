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
import { FlaskConical, Sparkles, Loader2, ArrowRight } from "lucide-react";

export default function ScoresPage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["ai-experiments", orgId],
    queryFn: () => ai.experimentIdeas.get(orgId),
    enabled: !!orgId,
  });

  const { data: summary } = useQuery({
    queryKey: ["ai-summary", orgId],
    queryFn: () => ai.summary(orgId),
    enabled: !!orgId,
  });

  const generate = useMutation({
    mutationFn: () => ai.experimentIdeas.generate(orgId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-experiments", orgId] });
      qc.invalidateQueries({ queryKey: ["ai-summary", orgId] });
    },
  });

  if (isLoading) return <Skeleton className="h-64" />;

  const items = data?.ideas || data?.items || [];
  const hasKey = summary?.has_api_key ?? false;

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Experiment Recommendations</h1>
          <p className="text-muted-foreground">
            Ranked hypotheses weighted by your 7-lens expert framework
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
            icon={FlaskConical}
            title="No experiment ideas yet"
            description={
              hasKey
                ? "Click 'Generate with Claude' to get prioritised experiment recommendations based on your product context, competitors, and lens weights."
                : "Add your Anthropic API key in Settings to generate experiment ideas with Claude."
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
            {items.map((exp: Record<string, unknown>, i: number) => (
              <Card key={i}>
                <CardContent className="pt-5 pb-5">
                  <div className="flex items-start gap-4">
                    <div className="flex items-center justify-center w-8 h-8 rounded-full bg-primary text-primary-foreground font-bold text-sm shrink-0 mt-0.5">
                      {i + 1}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <p className="font-semibold text-sm">{exp.title as string}</p>
                        {exp.expected_impact && (
                          <Badge variant="secondary" className="text-[10px]">
                            {exp.expected_impact as string} impact
                          </Badge>
                        )}
                        {exp.effort_estimate && (
                          <Badge variant="outline" className="text-[10px]">
                            {exp.effort_estimate as string} effort
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">{exp.hypothesis as string}</p>
                      {exp.product_area && (
                        <p className="text-xs text-muted-foreground mt-1">
                          Area: {exp.product_area as string}
                        </p>
                      )}
                      {exp.success_metric && (
                        <p className="text-xs mt-1.5 p-2 bg-zinc-50 dark:bg-zinc-900 rounded">
                          <span className="font-medium">Success metric:</span> {exp.success_metric as string}
                        </p>
                      )}
                      <LensBreakdown analysis={exp.lens_analysis as Record<string, string>} />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="flex items-center justify-between p-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50">
            <p className="text-sm text-muted-foreground">
              See your weekly summary of all intelligence.
            </p>
            <Link href="/digests">
              <Button variant="outline" size="sm">
                Weekly digests <ArrowRight className="h-3 w-3 ml-1" />
              </Button>
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
