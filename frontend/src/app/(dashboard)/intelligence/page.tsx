"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { intel, competitors, type IntelFeed } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { Radar, Globe, MessageSquare, GraduationCap, Scan, Loader2, ChevronDown, ChevronUp } from "lucide-react";

const SOURCE_COLORS: Record<string, string> = {
  firecrawl: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
  perplexity: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  hackernews: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
  reddit: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  academic: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
};

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export default function IntelligencePage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";
  const qc = useQueryClient();

  const [searchQuery, setSearchQuery] = useState("");
  const [academicQuery, setAcademicQuery] = useState("");

  const { data: comps } = useQuery({
    queryKey: ["competitors", orgId],
    queryFn: () => competitors.list(orgId),
    enabled: !!orgId,
  });

  const { data: feeds, isLoading } = useQuery({
    queryKey: ["intel-feeds", orgId],
    queryFn: () => intel.feeds(orgId),
    enabled: !!orgId,
  });

  const invalidateFeeds = () => qc.invalidateQueries({ queryKey: ["intel-feeds", orgId] });

  const scanCompetitors = useMutation({
    mutationFn: async () => {
      if (!comps || comps.length === 0) return;
      await Promise.allSettled(
        comps.map((c) => intel.scrapeCompetitor(orgId, { competitor_id: c.id }))
      );
    },
    onSuccess: invalidateFeeds,
  });

  const webSearch = useMutation({
    mutationFn: (query: string) => intel.webSearch(orgId, { query }),
    onSuccess: () => { setSearchQuery(""); invalidateFeeds(); },
  });

  const socialListen = useMutation({
    mutationFn: async () => {
      await Promise.allSettled([
        intel.hackernewsScan(orgId, {}),
        intel.redditScan(orgId, {}),
      ]);
    },
    onSuccess: invalidateFeeds,
  });

  const academicSearch = useMutation({
    mutationFn: (query: string) => intel.academicSearch(orgId, { query }),
    onSuccess: () => { setAcademicQuery(""); invalidateFeeds(); },
  });

  const sortedFeeds = [...(feeds || [])].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Intelligence Hub</h1>
        <p className="text-muted-foreground">
          Real-time market signals from web scraping, social listening, and academic research
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* Scan Competitors */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Scan className="h-4 w-4" /> Scan Competitors
            </CardTitle>
            <CardDescription className="text-xs">
              Scrape competitor websites for pricing, features, and positioning
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              size="sm"
              className="w-full"
              onClick={() => scanCompetitors.mutate()}
              disabled={scanCompetitors.isPending || !comps || comps.length === 0}
            >
              {scanCompetitors.isPending ? (
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
              ) : (
                <Scan className="h-3 w-3 mr-1" />
              )}
              {scanCompetitors.isPending ? "Scanning..." : "Scan All"}
            </Button>
          </CardContent>
        </Card>

        {/* Search News */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Globe className="h-4 w-4" /> Search News
            </CardTitle>
            <CardDescription className="text-xs">
              Find latest competitor moves and market trends
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search query..."
              className="h-8 text-xs"
              onKeyDown={(e) => {
                if (e.key === "Enter" && searchQuery.trim()) webSearch.mutate(searchQuery.trim());
              }}
            />
            <Button
              size="sm"
              className="w-full"
              onClick={() => webSearch.mutate(searchQuery.trim())}
              disabled={!searchQuery.trim() || webSearch.isPending}
            >
              {webSearch.isPending ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Globe className="h-3 w-3 mr-1" />}
              {webSearch.isPending ? "Searching..." : "Search"}
            </Button>
          </CardContent>
        </Card>

        {/* Social Listening */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <MessageSquare className="h-4 w-4" /> Social Listening
            </CardTitle>
            <CardDescription className="text-xs">
              Scan HackerNews and Reddit for mentions
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              size="sm"
              className="w-full"
              onClick={() => socialListen.mutate()}
              disabled={socialListen.isPending}
            >
              {socialListen.isPending ? (
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
              ) : (
                <MessageSquare className="h-3 w-3 mr-1" />
              )}
              {socialListen.isPending ? "Scanning..." : "Scan Social"}
            </Button>
          </CardContent>
        </Card>

        {/* Academic Research */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <GraduationCap className="h-4 w-4" /> Academic Research
            </CardTitle>
            <CardDescription className="text-xs">
              Search for relevant academic papers and studies
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Input
              value={academicQuery}
              onChange={(e) => setAcademicQuery(e.target.value)}
              placeholder="Research topic..."
              className="h-8 text-xs"
              onKeyDown={(e) => {
                if (e.key === "Enter" && academicQuery.trim()) academicSearch.mutate(academicQuery.trim());
              }}
            />
            <Button
              size="sm"
              className="w-full"
              onClick={() => academicSearch.mutate(academicQuery.trim())}
              disabled={!academicQuery.trim() || academicSearch.isPending}
            >
              {academicSearch.isPending ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <GraduationCap className="h-3 w-3 mr-1" />}
              {academicSearch.isPending ? "Searching..." : "Search"}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Feed */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Intelligence Feed</h2>
        {isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
        ) : sortedFeeds.length === 0 ? (
          <Card>
            <EmptyState
              icon={Radar}
              title="No intelligence gathered yet"
              description="Use the actions above to scan competitors, search the web, listen to social channels, or search academic papers."
            />
          </Card>
        ) : (
          <div className="space-y-3">
            {sortedFeeds.map((f) => (
              <FeedItem key={f.id} item={f} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function summarizeFeed(source: string, raw: string): string {
  try {
    const data = JSON.parse(raw);
    if (source === "hackernews" && data.hits) {
      const titles = data.hits.slice(0, 5).map((h: { title?: string }) => h.title).filter(Boolean);
      return titles.length ? `Found ${data.hits.length} results:\n${titles.map((t: string) => `• ${t}`).join("\n")}` : "No results found.";
    }
    if (source === "reddit" && data.posts) {
      const titles = data.posts.slice(0, 5).map((p: { title?: string }) => p.title).filter(Boolean);
      return titles.length ? `Found ${data.posts.length} posts:\n${titles.map((t: string) => `• ${t}`).join("\n")}` : "No posts found.";
    }
    if (source === "perplexity" && data.answer) return data.answer;
    if (source === "firecrawl" && data.markdown) return data.markdown.slice(0, 500);
    if (data.text) return data.text;
    if (data.answer) return data.answer;
    if (data.content) return data.content;
  } catch { /* not JSON, return raw */ }
  return raw;
}

function FeedItem({ item }: { item: IntelFeed }) {
  const [expanded, setExpanded] = useState(false);
  const display = summarizeFeed(item.source, item.content);
  const preview = display.slice(0, 300);
  const hasMore = display.length > 300;

  return (
    <Card>
      <CardContent className="pt-4 pb-3">
        <div className="flex items-center gap-2 mb-2">
          <Badge variant="secondary" className={`text-[10px] ${SOURCE_COLORS[item.source] || ""}`}>
            {item.source}
          </Badge>
          <span className="text-sm text-muted-foreground">{item.query}</span>
          <span className="text-xs text-muted-foreground ml-auto">{timeAgo(item.created_at)}</span>
        </div>
        <p className="text-sm text-muted-foreground whitespace-pre-line">
          {expanded ? display : preview}
          {hasMore && !expanded && "..."}
        </p>
        {hasMore && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-muted-foreground hover:text-foreground mt-1 flex items-center gap-1"
          >
            {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {expanded ? "Show less" : "Show more"}
          </button>
        )}
      </CardContent>
    </Card>
  );
}
