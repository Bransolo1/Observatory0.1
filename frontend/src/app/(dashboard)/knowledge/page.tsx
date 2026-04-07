"use client";

import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { knowledge } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { BookOpen, Upload, FileText } from "lucide-react";

export default function KnowledgePage() {
  const { currentOrg } = useAuth();
  const orgId = currentOrg?.id || "";
  const fileInputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [uploading, setUploading] = useState(false);

  const { data: docs, isLoading } = useQuery({
    queryKey: ["knowledge", orgId],
    queryFn: () => knowledge.list(orgId),
    enabled: !!orgId,
  });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => knowledge.upload(orgId, file, file.name, "research"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge", orgId] });
      setUploading(false);
    },
  });

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) { setUploading(true); uploadMutation.mutate(file); }
  };

  if (isLoading) return <Skeleton className="h-64" />;

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Knowledge Base</h1>
          <p className="text-muted-foreground">
            Historic research, survey results, and internal documents that enrich analysis
          </p>
        </div>
        <input ref={fileInputRef} type="file" onChange={handleFile} accept=".pdf,.docx,.pptx" className="hidden" />
        <Button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          <Upload className="h-4 w-4 mr-1.5" /> {uploading ? "Uploading..." : "Upload document"}
        </Button>
      </div>

      {!docs || docs.length === 0 ? (
        <Card>
          <EmptyState
            icon={BookOpen}
            title="Upload research to enrich analysis"
            description="Observatory extracts structured findings from PDFs, Word docs, and presentations — customer research, competitor analyses, strategy docs — and makes them searchable. Uploaded knowledge is cited in insights and experiment recommendations."
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {docs.map((d) => (
            <Card key={d.id}>
              <CardContent className="pt-5">
                <div className="flex items-start gap-3">
                  <FileText className="h-5 w-5 text-muted-foreground mt-0.5" />
                  <div className="flex-1">
                    <p className="font-medium">{d.title}</p>
                    <p className="text-xs text-muted-foreground">{d.doc_type} · {d.chunk_count} chunks · {d.status}</p>
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
