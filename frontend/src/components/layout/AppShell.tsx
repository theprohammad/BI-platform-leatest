import type { ReactNode } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import {
  Brain,
  LayoutGrid,
  Radar,
  Search,
  Users,
  Target,
  Globe,
  Sparkles,
  Mail,
  FileText,
  Settings as SettingsIcon,
  Bell,
  ChevronLeft,
  Menu,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { useActiveOrg } from "@/hooks/use-active-org";
import { useQuery } from "@tanstack/react-query";
import { fetchPipeline } from "@/services/intelligence";
import { CommandPalette } from "@/components/premium/CommandPalette";

type NavItem = {
  to: string;
  label: string;
  icon: typeof LayoutGrid;
  badgeKey?: "leads";
};

const NAV_GROUPS: { heading: string | null; items: NavItem[] }[] = [
  {
    heading: null,
    items: [
      { to: "/", label: "Dashboard", icon: LayoutGrid },
      { to: "/workspace", label: "Intelligence Workspace", icon: Brain },
      { to: "/intelligence", label: "New Analysis", icon: Sparkles },
    ],
  },
  {
    heading: "Research",
    items: [
      { to: "/market-research", label: "Market Research", icon: Search },
      { to: "/competitors", label: "Competitors", icon: Users },
      { to: "/monitoring", label: "Monitoring", icon: Radar },
      { to: "/website-audit", label: "Website Audit", icon: Globe },
      {
        to: "/opportunity-scoring",
        label: "Opportunity Engine",
        icon: Target,
      },
    ],
  },
  {
    heading: "Growth",
    items: [
      {
        to: "/lead-generation",
        label: "Lead Intelligence",
        icon: Target,
        badgeKey: "leads",
      },
      { to: "/reports", label: "Reports", icon: FileText },
    ],
  },
];

function BrandMark() {
  return (
    <div className="relative grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-violet-500 via-fuchsia-500 to-purple-600 shadow-lg shadow-fuchsia-500/25">
      <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-white/20 to-transparent" />
      <Sparkles className="relative h-[18px] w-[18px] text-white" strokeWidth={2.5} />
    </div>
  );
}

function SidebarBody({
  collapsed,
  onNavigate,
  onToggleCollapse,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
  onToggleCollapse?: () => void;
}) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { data: pipeline } = useQuery({
    queryKey: ["pipeline"],
    queryFn: fetchPipeline,
    staleTime: 60_000,
  });
  const leadCount = pipeline?.total_leads ?? 0;

  return (
    <div className="flex h-full flex-col">
      <div className={cn("px-5 pt-6 pb-6", collapsed && "px-3")}>
        <Link to="/" className="flex items-center gap-3" onClick={onNavigate}>
          <BrandMark />
          {!collapsed && (
            <div className="leading-tight">
              <div className="text-[15px] font-semibold tracking-tight">Sentient</div>
              <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Intelligence OS
              </div>
            </div>
          )}
        </Link>
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto px-3">
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi} className="space-y-0.5">
            {group.heading && !collapsed && (
              <div className="px-3 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/60">
                {group.heading}
              </div>
            )}
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
              const badge = item.badgeKey === "leads" && leadCount > 0 ? leadCount : null;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  onClick={onNavigate}
                  title={collapsed ? item.label : undefined}
                  className={cn(
                    "group relative flex items-center gap-3 rounded-xl px-3 py-2 text-[13px] font-medium transition-all duration-150",
                    active
                      ? "bg-[var(--surface-2)] text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.2)]"
                      : "text-muted-foreground hover:bg-white/[0.03] hover:text-foreground",
                    collapsed && "justify-center px-0",
                  )}
                >
                  {active && (
                    <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-to-b from-violet-400 to-fuchsia-500" />
                  )}
                  <Icon
                    className={cn(
                      "h-[17px] w-[17px] shrink-0 transition-colors",
                      active
                        ? "text-fuchsia-300"
                        : "text-muted-foreground group-hover:text-foreground",
                    )}
                  />
                  {!collapsed && (
                    <>
                      <span className="truncate">{item.label}</span>
                      {badge !== null && (
                        <span className="ml-auto rounded-md bg-fuchsia-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-fuchsia-300">
                          {badge}
                        </span>
                      )}
                    </>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-[var(--hairline)] px-3 py-3">
        <Link
          to="/settings"
          onClick={onNavigate}
          className={cn(
            "flex items-center gap-3 rounded-xl px-3 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-white/[0.03] hover:text-foreground",
            collapsed && "justify-center px-0",
          )}
          title={collapsed ? "Settings" : undefined}
        >
          <SettingsIcon className="h-[17px] w-[17px] shrink-0" />
          {!collapsed && "Settings"}
        </Link>
        <button
          type="button"
          onClick={onToggleCollapse}
          className="mt-1 hidden lg:flex w-full items-center justify-center gap-2 rounded-lg px-3 py-1.5 text-[11px] text-muted-foreground hover:bg-white/[0.03] hover:text-foreground transition-colors"
        >
          <ChevronLeft
            className={cn("h-3.5 w-3.5 transition-transform", collapsed && "rotate-180")}
          />
          {!collapsed && "Collapse"}
        </button>
      </div>
    </div>
  );
}

export function AppShell({ children, title }: { children: ReactNode; title?: string }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const { activeOrg } = useActiveOrg();
  const company = activeOrg?.name;

  const sidebarWidth = collapsed ? "lg:w-20" : "lg:w-64";
  const contentOffset = collapsed ? "lg:pl-20" : "lg:pl-64";

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Ambient background wash */}
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(900px_500px_at_15%_-10%,rgba(139,92,246,0.10),transparent),radial-gradient(800px_450px_at_100%_0%,rgba(217,70,239,0.06),transparent)]" />
      <div className="pointer-events-none fixed inset-0 -z-10 grid-lines opacity-[0.4]" />

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 hidden border-r border-[var(--hairline)] bg-[var(--sidebar)]/70 backdrop-blur-xl lg:block transition-[width] duration-200",
          sidebarWidth,
        )}
      >
        <SidebarBody collapsed={collapsed} onToggleCollapse={() => setCollapsed((c) => !c)} />
      </aside>

      {/* Mobile sidebar */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 border-r border-[var(--hairline)] bg-[var(--sidebar)] shadow-2xl">
            <SidebarBody collapsed={false} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className={cn("transition-[padding] duration-200", contentOffset)}>
        {/* Top bar */}
        <header className="sticky top-0 z-20 border-b border-[var(--hairline)] bg-background/70 backdrop-blur-xl">
          <div className="flex h-16 items-center gap-3 px-4 lg:px-8">
            <button
              className="lg:hidden inline-flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--hairline)] text-muted-foreground hover:text-foreground"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
            >
              <Menu className="h-4 w-4" />
            </button>

            {/* Workspace breadcrumb */}
            <div className="flex items-center gap-2 min-w-0">
              {company ? (
                <>
                  <div className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-violet-500/25 to-fuchsia-500/25 text-[10px] font-bold text-foreground border border-[var(--hairline)]">
                    {company
                      .split(/\s+/)
                      .slice(0, 2)
                      .map((w) => w[0])
                      .join("")
                      .toUpperCase()}
                  </div>
                  <span className="text-sm font-medium truncate">{company}</span>
                </>
              ) : (
                <span className="text-sm font-medium text-muted-foreground">
                  No organization yet
                </span>
              )}
              {title && (
                <>
                  <span className="text-muted-foreground/40">/</span>
                  <span className="text-sm text-muted-foreground truncate">{title}</span>
                </>
              )}
            </div>

            <div className="ml-auto flex items-center gap-3">
              <button
                onClick={() =>
                  window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))
                }
                className="hidden md:flex items-center gap-2 rounded-xl border border-[var(--hairline)] bg-[var(--surface)]/60 px-3 py-1.5 text-xs text-muted-foreground w-72 transition-colors hover:border-[color-mix(in_oklch,var(--primary)_30%,transparent)] hover:text-foreground"
              >
                <Search className="h-3.5 w-3.5" />
                <span>Search intelligence…</span>
                <kbd className="ml-auto rounded border border-[var(--hairline)] bg-[var(--surface-2)] px-1.5 py-0.5 font-mono text-[10px]">
                  ⌘K
                </kbd>
              </button>
              <button
                aria-label="Notifications"
                className="relative grid h-9 w-9 place-items-center rounded-xl border border-[var(--hairline)] text-muted-foreground transition-colors hover:text-foreground hover:bg-[var(--surface)]"
              >
                <Bell className="h-4 w-4" />
                <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-fuchsia-400" />
              </button>
              <div className="grid h-9 w-9 place-items-center rounded-full bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-[11px] font-bold text-white ring-2 ring-[var(--surface)]">
                JS
              </div>
            </div>
          </div>
        </header>

        <main className="px-4 py-8 lg:px-10 lg:py-10">{children}</main>
      </div>
      <CommandPalette />
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="min-w-0">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.02em] text-gradient sm:text-[34px]">
          {title}
        </h1>
        {description && (
          <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyAnalysis({ label }: { label: string }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-dashed border-[var(--hairline)] bg-[var(--surface)]/40 px-6 py-16 text-center">
      <div className="pointer-events-none absolute left-1/2 top-0 h-40 w-40 -translate-x-1/2 rounded-full bg-fuchsia-500/[0.07] blur-3xl" />
      <div className="relative">
        <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-[var(--hairline)] bg-[var(--surface-2)]">
          <Sparkles className="h-6 w-6 text-fuchsia-300" />
        </div>
        <h3 className="mt-4 text-[15px] font-semibold">No {label} yet</h3>
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted-foreground">
          Run an analysis to populate this view with verified, cited intelligence.
        </p>
        <div className="mt-5">
          <Link
            to="/intelligence"
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-500 to-fuchsia-500 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-fuchsia-500/20 transition-transform hover:scale-[1.02]"
          >
            <Sparkles className="h-4 w-4" />
            New Analysis
          </Link>
        </div>
      </div>
    </div>
  );
}
