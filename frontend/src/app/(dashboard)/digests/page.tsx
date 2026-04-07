"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { ai } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { Newspaper, Sparkles, Loader2 } from "lucide-react";

export default function DigestsPage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["ai-digest", orgId],
    queryFn: () => ai.digest.get(orgId),
    enabled: !!orgId,
  });

  const { data: summary } = useQuery({
    queryKey: ["ai-summary", orgId],
    queryFn: () => ai.summary(orgId),
    enabled: !!orgId,
  });

  const generate = useMutation({
    mutationFn: () => ai.digest.generate(orgId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-digest", orgId] });
      qc.invalidateQueries({ queryKey: ["ai-summary", orgId] });
    },
  });

  if (isLoading) return <Skeleton className="h-64" />;

  const digest = data?.digest as Record<string, unknown> | null;
  const hasKey = summary?.has_api_key ?? false;

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Intelligence Digest</h1>
          <p className="text-muted-foreground">
            Executive summary of all intelligence — competitive, friction, experiments, and research
          </p>
        </div>
        <Button
          onClick={() => generate.mutate()}
          disabled={!hasKey || generate.isPending}
          size="sm"
        >
          {generate.isPending ? (
            <><Loader2 className="h-3 w-3 mr-1 animate-spin" /> Generating…</>
          ) : digest ? (
            <><Sparkles className="h-3 w-3 mr-1" /> Regenerate</>
          ) : (
            <><Sparkles className="h-3 w-3 mr-1" /> Generate digest</>
          )}
        </Button>
      </div>

      {!digest ? (
        <Card>
          <EmptyState
            icon={Newspaper}
            title="No digest generated yet"
            description={
              hasKey
                ? "Click 'Generate digest' to create an executive summary from all your intelligence. The more you've generated (friction scenarios, battlecards, experiments, insights, research briefs), the richer the digest."
                : "Add your Anthropic API key in Settings to generate intelligence digests."
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

          {/* TL;DR */}
          <Card className="border-2 border-zinc-900 dark:border-white">
            <CardHeader>
              <CardTitle className="text-base">TL;DR</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm">{digest.tldr as string}</p>
            </CardContent>
          </Card>

          {/* Sections */}
          {digest.sections && typeof digest.sections === "object" && (
            <div className="space-y-4">
              {Object.entries(digest.sections as Record<string, string>).map(([key, content]) => (
                <Card key={key}>
                  <CardHeader>
                    <CardTitle className="text-base capitalize">
                      {key.replace(/_/g, " ")}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm whitespace-pre-wrap">{content}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* Top actions */}
          {(digest.top_actions as string[])?.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Recommended actions</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {(digest.top_actions as string[]).map((action, i) => (
                    <li key={i} className="flex gap-2 text-sm">
                      <span className="shrink-0 w-5 h-5 rounded-full bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 flex items-center justify-center text-xs font-bold">
                        {i + 1}
                      </span>
                      <span>{action}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
