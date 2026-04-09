"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  AlertTriangle,
  BarChart3,
  BookOpen,
  FileSearch,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  MessageSquare,
  Newspaper,
  PoundSterling,
  Radar,
  Shield,
  Swords,
  Settings,
  LogOut,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/lib/auth-context";
import { OrgSwitcher } from "./org-switcher";

const navGroups = [
  {
    label: "Command",
    items: [
      { title: "Chat", href: "/chat", icon: MessageSquare },
      { title: "Overview", href: "/overview", icon: Gauge },
    ],
  },
  {
    label: "1. Inputs",
    items: [
      { title: "Competitors", href: "/competitors", icon: Swords },
      { title: "Knowledge Base", href: "/knowledge", icon: BookOpen },
      { title: "Research", href: "/research", icon: FileSearch },
    ],
  },
  {
    label: "2. Intelligence",
    items: [
      { title: "Intelligence Hub", href: "/intelligence", icon: Radar },
      { title: "Friction Signals", href: "/friction", icon: AlertTriangle },
      { title: "Insights", href: "/insights", icon: LayoutDashboard },
      { title: "Battlecards", href: "/battlecards", icon: Shield },
    ],
  },
  {
    label: "3. Decisions",
    items: [
      { title: "Priority Scores", href: "/scores", icon: BarChart3 },
      { title: "Weekly Digests", href: "/digests", icon: Newspaper },
    ],
  },
];

export function AppSidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <Sidebar>
      <SidebarHeader className="p-4">
        <Link href="/overview" className="flex items-center gap-2">
          <FlaskConical className="h-6 w-6" />
          <span className="text-lg font-bold tracking-tight">Observatory</span>
        </Link>
        <div className="mt-3">
          <OrgSwitcher />
        </div>
      </SidebarHeader>

      <Separator />

      <SidebarContent>
        {navGroups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      render={<Link href={item.href} />}
                      isActive={pathname.startsWith(item.href)}
                    >
                      <item.icon className="h-4 w-4" />
                      <span>{item.title}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}

        <SidebarGroup>
          <SidebarGroupLabel>System</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  render={<Link href="/costs" />}
                  isActive={pathname === "/costs"}
                >
                  <PoundSterling className="h-4 w-4" />
                  <span>Cost Controls</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton
                  render={<Link href="/settings" />}
                  isActive={pathname === "/settings"}
                >
                  <Settings className="h-4 w-4" />
                  <span>Settings</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="p-4">
        <p className="text-[10px] text-muted-foreground mb-2">Powered by Claude AI</p>
        <div className="flex items-center justify-between">
          <div className="text-sm truncate">
            <p className="font-medium truncate">{user?.name}</p>
            <p className="text-muted-foreground truncate text-xs">{user?.email}</p>
          </div>
          <button
            onClick={logout}
            className="rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
