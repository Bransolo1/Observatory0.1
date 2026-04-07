"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { competitors, intel } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { Swords, Plus, X, ExternalLink, Scan, Loader2 } from "lucide-react";

export default function CompetitorsPage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");

  const { data: list, isLoading } = useQuery({
    queryKey: ["competitors", orgId],
    queryFn: () => competitors.list(orgId),
    enabled: !!orgId,
  });

  const addMutation = useMutation({
    mutationFn: () => competitors.create(orgId, { name, website_url: url || undefined, description: description || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["competitors", orgId] });
      setName(""); setUrl(""); setDescription(""); setAdding(false);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => competitors.delete(orgId, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["competitors", orgId] }),
  });

  const [scanningId, setScanningId] = useState<string | null>(null);
  const [scanAllLoading, setScanAllLoading] = useState(false);

  const deepScanMutation = useMutation({
    mutationFn: (competitorId: string) => intel.deepAnalysis(orgId, { competitor_id: competitorId }),
    onSuccess: () => setScanningId(null),
    onError: () => setScanningId(null),
  });

  const scanAll = async () => {
    if (!list || list.length === 0) return;
    setScanAllLoading(true);
    try {
      await Promise.allSettled(
        list.map((c) => intel.scrapeCompetitor(orgId, { competitor_id: c.id }))
      );
    } finally {
      setScanAllLoading(false);
    }
  };

  if (isLoading) return <div className="space-y-3"><Skeleton className="h-10 w-48" /><Skeleton className="h-32" /></div>;

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Competitors</h1>
          <p className="text-muted-foreground">Track pricing, features, messaging, and market moves</p>
        </div>
        <div className="flex gap-2">
          {list && list.length > 0 && (
            <Button variant="outline" onClick={scanAll} disabled={scanAllLoading}>
              {scanAllLoading ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Scan className="h-4 w-4 mr-1" />}
              Scan All
            </Button>
          )}
          {!adding && (
            <Button onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4 mr-1" /> Add competitor
            </Button>
          )}
        </div>
      </div>

      {adding && (
        <Card>
          <CardContent className="pt-6 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="name" className="text-xs">Name</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Lattice" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="url" className="text-xs">Website</Label>
                <Input id="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="desc" className="text-xs">Description (optional)</Label>
              <Input id="desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Brief description" />
            </div>
            <div className="flex gap-2 pt-2">
              <Button onClick={() => addMutation.mutate()} disabled={!name.trim() || addMutation.isPending}>
                {addMutation.isPending ? "Adding..." : "Add competitor"}
              </Button>
              <Button variant="ghost" onClick={() => { setAdding(false); setName(""); setUrl(""); setDescription(""); }}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {!list || list.length === 0 ? (
        <Card>
          <EmptyState
            icon={Swords}
            title="No competitors tracked yet"
            description="Add competitors to monitor their pricing, feature launches, messaging, and market positioning. Observatory scans weekly and surfaces meaningful changes."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {list.map((c) => (
            <Card key={c.id} className="group">
              <CardContent className="pt-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-semibold">{c.name}</h3>
                      {c.website_url && (
                        <a href={c.website_url} target="_blank" rel="noreferrer" className="text-muted-foreground hover:text-foreground">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}
                    </div>
                    {c.description && <p className="text-sm text-muted-foreground">{c.description}</p>}
                    <p className="text-xs text-muted-foreground mt-2">No changes detected yet — first scan pending</p>
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setScanningId(c.id);
                        deepScanMutation.mutate(c.id);
                      }}
                      disabled={scanningId === c.id && deepScanMutation.isPending}
                      className="text-xs h-7"
                    >
                      {scanningId === c.id && deepScanMutation.isPending ? (
                        <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                      ) : (
                        <Scan className="h-3 w-3 mr-1" />
                      )}
                      Deep Scan
                    </Button>
                    <button
                      onClick={() => deleteMutation.mutate(c.id)}
                      className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground transition-opacity"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
