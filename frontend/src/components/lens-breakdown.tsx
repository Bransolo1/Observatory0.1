"use client";

import { LENS_DEFINITIONS } from "@/lib/lenses";
import { Shield } from "lucide-react";

export function LensBreakdown({ analysis }: { analysis: Record<string, string> | undefined | null }) {
  if (!analysis || Object.keys(analysis).length === 0) return null;
  return (
    <div className="space-y-2 mt-3 pt-3 border-t border-zinc-200 dark:border-zinc-800">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Expert lens analysis
      </p>
      {Object.entries(analysis).map(([key, text]) => {
        const def = LENS_DEFINITIONS.find((l) => l.key === key);
        const Icon = def?.icon || Shield;
        return (
          <div key={key} className="flex gap-2 text-xs">
            <div className="shrink-0 w-5 h-5 rounded bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center mt-0.5">
              <Icon className="h-3 w-3" />
            </div>
            <div className="flex-1">
              <span className="font-medium">{def?.title || key}:</span>{" "}
              <span className="text-muted-foreground">{text}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
