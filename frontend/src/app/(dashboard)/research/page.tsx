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
import { FileSearch, Sparkles, Loader2, Copy, CheckCircle2 } from "lucide-react";
import { useState } from "react";

const PRIORITY_COLOR: Record<string, string> = {
  high: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  medium: "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-300",
  low: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
};

export default function ResearchPage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["ai-research", orgId],
    queryFn: () => ai.researchGaps.get(orgId),
    enabled: !!orgId,
  });

  const { data: summary } = useQuery({
    queryKey: ["ai-summary", orgId],
    queryFn: () => ai.summary(orgId),
    enabled: !!orgId,
  });

  const generate = useMutation({
    mutationFn: () => ai.researchGaps.generate(orgId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-research", orgId] });
      qc.invalidateQueries({ queryKey: ["ai-summary", orgId] });
    },
  });

  if (isLoading) return <Skeleton className="h-64" />;

  const items = (data?.items || []) as Record<string, string>[];
  const hasKey = summary?.has_api_key ?? false;

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Research Pipeline</h1>
          <p className="text-muted-foreground">
            Ask Claude to find what you don&apos;t know yet, then commission research to fill the gaps
          </p>
        </div>
        <Button
          onClick={() => generate.mutate()}
          disabled={!hasKey || generate.isPending}
          size="sm"
        >
          {generate.isPending ? (
            <><Loader2 className="h-3 w-3 mr-1 animate-spin" /> Detecting gaps…</>
          ) : items.length > 0 ? (
            <><Sparkles className="h-3 w-3 mr-1" /> Re-detect gaps</>
          ) : (
            <><Sparkles className="h-3 w-3 mr-1" /> Detect knowledge gaps</>
          )}
        </Button>
      </div>

      {items.length === 0 ? (
        <Card>
          <EmptyState
            icon={FileSearch}
            title="No research briefs yet"
            description={
              hasKey
                ? "Click 'Detect knowledge gaps' to have Claude analyse what your team would need to know to make confident decisions — and produce structured research briefs you can commission directly."
                : "Add your Anthropic API key in Settings to detect knowledge gaps with Claude."
            }
            action={hasKey ? undefined : { label: "Add API key", href: "/settings" }}
            secondary={{ label: "Upload existing research", href: "/knowledge" }}
          />
        </Card>
      ) : (
        <>
          {data?.generated_at && (
            <p className="text-xs text-muted-foreground">
              Generated {new Date(data.generated_at).toLocaleString()}
            </p>
          )}
          <div className="space-y-4">
            {items.map((brief, i) => (
              <ResearchBriefCard key={i} brief={brief} index={i} />
            ))}
          </div>

          <div className="flex items-center justify-between p-4 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50">
            <p className="text-sm text-muted-foreground">
              Have existing research? Upload it to enrich future analyses.
            </p>
            <Link href="/knowledge">
              <Button variant="outline" size="sm">
                Knowledge base →
              </Button>
            </Link>
          </div>
        </>
      )}
    </div>
  );
}

function ResearchBriefCard({ brief, index }: { brief: Record<string, string>; index: number }) {
  const [copied, setCopied] = useState(false);

  const copyBrief = () => {
    const text = `RESEARCH BRIEF: ${brief.title}\n\nKnowledge Gap: ${brief.knowledge_gap}\nObjective: ${brief.objective}\nMethodology: ${brief.methodology}\nSample: ${brief.sample_size}\nCost: ${brief.cost_estimate}\nTimeline: ${brief.timeline}\nExpected Value: ${brief.expected_value}`;
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <Badge variant="outline" className={PRIORITY_COLOR[brief.priority] || ""}>
                {brief.priority} priority
              </Badge>
              {brief.methodology && (
                <Badge variant="secondary" className="text-[10px]">
                  {brief.methodology}
                </Badge>
              )}
              {brief.related_area && (
                <span className="text-xs text-muted-foreground">{brief.related_area}</span>
              )}
            </div>
            <h3 className="font-semibold text-sm">{brief.title}</h3>
            <p className="text-sm text-muted-foreground mt-1">{brief.knowledge_gap}</p>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3 p-3 bg-zinc-50 dark:bg-zinc-900 rounded-lg text-xs">
              <div>
                <p className="text-muted-foreground">Objective</p>
                <p className="font-medium mt-0.5">{brief.objective}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Sample</p>
                <p className="font-medium mt-0.5">{brief.sample_size}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Cost estimate</p>
                <p className="font-medium mt-0.5">{brief.cost_estimate}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Timeline</p>
                <p className="font-medium mt-0.5">{brief.timeline}</p>
              </div>
            </div>

            {brief.expected_value && (
              <p className="text-xs text-muted-foreground mt-2">
                <span className="font-medium">Unlocks:</span> {brief.expected_value}
              </p>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={copyBrief}
            className="shrink-0"
          >
            {copied ? (
              <><CheckCircle2 className="h-3 w-3 mr-1" /> Copied</>
            ) : (
              <><Copy className="h-3 w-3 mr-1" /> Commission</>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
