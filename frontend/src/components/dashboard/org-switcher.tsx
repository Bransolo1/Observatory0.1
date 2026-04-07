"use client";

import { useAuth } from "@/lib/auth-context";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ChevronsUpDown } from "lucide-react";

export function OrgSwitcher() {
  const { currentOrg, orgs, role, switchOrg } = useAuth();

  if (!currentOrg) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="outline" className="w-full justify-between text-left h-auto py-2" />}
      >
        <div className="flex flex-col items-start gap-0.5 truncate">
          <span className="text-sm font-medium truncate">{currentOrg.name}</span>
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
            {role}
          </Badge>
        </div>
        <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56" align="start">
        {orgs.map((org) => (
          <DropdownMenuItem
            key={org.id}
            onClick={() => switchOrg(org.id)}
            className={org.id === currentOrg.id ? "bg-muted" : ""}
          >
            <div className="flex flex-col">
              <span>{org.name}</span>
              <span className="text-xs text-muted-foreground">{org.role}</span>
            </div>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
