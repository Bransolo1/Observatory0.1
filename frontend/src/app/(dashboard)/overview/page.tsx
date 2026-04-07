"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { ai, competitors, onboarding } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  AlertTriangle,
  ArrowRight,
  FlaskConical,
  Swords,
  Sparkles,
  Send,
  KeyRound,
  Loader2,
} from "lucide-react";

export default function OverviewPage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";
  const qc = useQueryClient();

  const { data: summary } = useQuery({
    queryKey: ["ai-summary", orgId],
    queryFn: () => ai.summary(orgId),
    enabled: !!orgId,
  });

  const { data: onboardingState } = useQuery({
    queryKey: ["onboarding", orgId],
    queryFn: () => onboarding.get(orgId),
    enabled: !!orgId,
  });

  const { data: comps } = useQuery({
    queryKey: ["competitors", orgId],
    queryFn: () => competitors.list(orgId),
    enabled: !!orgId,
  });

  const analyzeCompetitor = useMutation({
    mutationFn: (competitorId: string) => ai.analyzeCompetitor(orgId, competitorId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-summary", orgId] });
      qc.invalidateQueries({ queryKey: ["competitors", orgId] });
    },
  });

  const genFriction = useMutation({
    mutationFn: () => ai.frictionScenarios.generate(orgId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ai-summary", orgId] }),
  });

  const genExperiments = useMutation({
    mutationFn: () => ai.experimentIdeas.generate(orgId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ai-summary", orgId] }),
  });

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const askClaude = useMutation({
    mutationFn: (q: string) => ai.ask(orgId, q),
    onSuccess: (r) => setAnswer(r.answer),
  });

  const hasKey = summary?.has_api_key ?? false;
  const firstCompetitor = comps?.[0];

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          {currentOrg?.name} — Intelligence Command
        </h1>
        <p className="text-muted-foreground">
          Inputs → Intelligence → Decisions. Run Claude against your product context.
        </p>
      </div>

      {!hasKey && (
        <Card className="border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-900">
          <CardContent className="pt-6 pb-6 flex items-start gap-4">
            <div className="shrink-0 w-10 h-10 rounded-xl bg-amber-500 text-white flex items-center justify-center">
              <KeyRound className="h-5 w-5" />
            </div>
            <div className="flex-1">
              <div className="font-semibold mb-1">Connect Claude to unlock intelligence</div>
              <p className="text-sm text-muted-foreground mb-3">
                Observatory uses Claude (Anthropic) to synthesize friction signals, competitor
                battlecards and experiment ideas from your configured context. Add an API key to
                get started.
              </p>
              <Link href="/settings">
                <Button size="sm">Add Anthropic API key</Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 3 hero Claude actions — linear narrative */}
      <div>
        <h2 className="font-semibold mb-3 text-sm uppercase tracking-wide text-muted-foreground">
          Generate with Claude
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <HeroAction
            step="1"
            icon={Swords}
            title="Analyse a competitor"
            desc={
              firstCompetitor
                ? `Run 3-lens battlecard on ${firstCompetitor.name}`
                : "Add a competitor first"
            }
            count={summary?.competitors_analyzed || 0}
            countLabel="analysed"
            disabled={!hasKey || !firstCompetitor || analyzeCompetitor.isPending}
            loading={analyzeCompetitor.isPending}
            onRun={() => firstCompetitor && analyzeCompetitor.mutate(firstCompetitor.id)}
            viewHref="/battlecards"
          />
          <HeroAction
            step="2"
            icon={AlertTriangle}
            title="Surface friction scenarios"
            desc="Claude hypothesises where users drop off based on your product areas"
            count={summary?.friction_scenarios || 0}
            countLabel="scenarios"
            disabled={!hasKey || genFriction.isPending}
            loading={genFriction.isPending}
            onRun={() => genFriction.mutate()}
            viewHref="/friction"
          />
          <HeroAction
            step="3"
            icon={FlaskConical}
            title="Recommend experiments"
            desc="Ranked hypotheses weighted by your academic/business/UX lens mix"
            count={summary?.experiment_ideas || 0}
            countLabel="ideas"
            disabled={!hasKey || genExperiments.isPending}
            loading={genExperiments.isPending}
            onRun={() => genExperiments.mutate()}
            viewHref="/scores"
          />
        </div>
      </div>

      {/* Ask Claude */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Sparkles className="h-4 w-4" /> Ask Claude
          </CardTitle>
          <CardDescription>
            Free-form question answered with your product context + 3-lens framework
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (question.trim()) askClaude.mutate(question.trim());
            }}
            className="flex gap-2"
          >
            <Input
              placeholder="e.g. What should we prioritise next quarter?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={!hasKey || askClaude.isPending}
              className="h-11"
            />
            <Button
              type="submit"
              disabled={!hasKey || askClaude.isPending || !question.trim()}
              className="h-11"
            >
              {askClaude.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </form>
          {answer && (
            <div className="mt-3 p-4 rounded-lg border bg-muted/50 text-sm whitespace-pre-wrap">
              {answer}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Context snapshot */}
      <div>
        <h2 className="font-semibold mb-3 text-sm uppercase tracking-wide text-muted-foreground">
          Your context
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            label="Product areas"
            value={onboardingState?.product_areas_count || 0}
            href="/settings"
          />
          <StatCard
            label="Competitors"
            value={onboardingState?.competitors_count || 0}
            href="/competitors"
          />
          <StatCard
            label="Data sources"
            value={onboardingState?.data_sources_count || 0}
            href="/settings"
          />
          <StatCard
            label="Expert lenses"
            value="7 active"
            sublabel="Click to adjust weights"
            href="/settings"
          />
        </div>
      </div>
    </div>
  );
}

function HeroAction({
  step,
  icon: Icon,
  title,
  desc,
  count,
  countLabel,
  disabled,
  loading,
  onRun,
  viewHref,
}: {
  step: string;
  icon: React.ElementType;
  title: string;
  desc: string;
  count: number;
  countLabel: string;
  disabled: boolean;
  loading: boolean;
  onRun: () => void;
  viewHref: string;
}) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="w-10 h-10 rounded-xl bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 flex items-center justify-center">
            <Icon className="h-5 w-5" />
          </div>
          <Badge variant="secondary" className="text-xs">
            Step {step}
          </Badge>
        </div>
        <CardTitle className="text-base mt-3">{title}</CardTitle>
        <CardDescription className="text-xs">{desc}</CardDescription>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col justify-end gap-2">
        <div className="text-xs text-muted-foreground">
          {count} {countLabel}
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={onRun} disabled={disabled} className="flex-1">
            {loading ? (
              <>
                <Loader2 className="h-3 w-3 mr-1 animate-spin" /> Generating…
              </>
            ) : (
              "Run"
            )}
          </Button>
          <Link href={viewHref}>
            <Button size="sm" variant="outline">
              <ArrowRight className="h-3 w-3" />
            </Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

function StatCard({
  label,
  value,
  sublabel,
  href,
}: {
  label: string;
  value: string | number;
  sublabel?: string;
  href: string;
}) {
  return (
    <Link href={href}>
      <Card className="hover:shadow-md transition-shadow cursor-pointer">
        <CardContent className="pt-4 pb-4">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-2xl font-bold mt-1">{value}</p>
          {sublabel && <p className="text-[10px] text-muted-foreground mt-0.5">{sublabel}</p>}
        </CardContent>
      </Card>
    </Link>
  );
}
