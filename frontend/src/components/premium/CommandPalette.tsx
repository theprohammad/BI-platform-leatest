/**
 * ⌘K command palette — navigation + live workspace search in one surface.
 * The signature "power user" interaction of the platform.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Brain,
  FileText,
  Globe,
  Lightbulb,
  Mail,
  Radar,
  Scale,
  Swords,
  Search,
  Sparkles,
  Target,
  Users,
  LayoutGrid,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { searchWorkspace } from "@/services/intelligence";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutGrid },
  { to: "/workspace", label: "Intelligence Workspace", icon: Brain },
  { to: "/intelligence", label: "New Analysis", icon: Sparkles },
  { to: "/market-research", label: "Market Research", icon: Search },
  { to: "/competitors", label: "Competitors", icon: Users },
  { to: "/lead-generation", label: "Lead Generation", icon: Target },
  { to: "/website-audit", label: "Website Audit", icon: Globe },
  { to: "/reports", label: "Reports", icon: FileText },
];

const SUGGESTED = [
  "competitors",
  "pricing",
  "positioning",
  "technology stack",
  "partnerships",
  "market size",
  "recent changes",
  "growth signals",
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const { data: results } = useQuery({
    queryKey: ["cmdk-search", query],
    queryFn: () => searchWorkspace(query),
    enabled: query.trim().length >= 2,
  });

  const go = (to: string) => {
    setOpen(false);
    setQuery("");
    navigate({ to });
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput
        placeholder="Search organizations, competitors, findings…"
        value={query}
        onValueChange={setQuery}
      />
      <CommandList>
        <CommandEmpty>No matches yet — try one of the suggestions below.</CommandEmpty>
        <CommandGroup heading="Navigate">
          {NAV.map((n) => (
            <CommandItem key={n.to} value={`nav ${n.label}`} onSelect={() => go(n.to)}>
              <n.icon className="mr-2 h-4 w-4 text-muted-foreground" />
              {n.label}
            </CommandItem>
          ))}
        </CommandGroup>
        {query.trim().length < 2 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Suggested searches">
              {SUGGESTED.map((s) => (
                <CommandItem key={s} value={`suggest ${s}`} onSelect={() => setQuery(s)}>
                  <Search className="mr-2 h-4 w-4 text-muted-foreground" />
                  {s}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
        {results && (
          <>
            {results.recommendations.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Recommendations">
                  {results.recommendations.map((r) => (
                    <CommandItem
                      key={r.id}
                      value={`rec ${r.title}`}
                      onSelect={() => go("/workspace")}
                    >
                      <Lightbulb className="mr-2 h-4 w-4 text-amber-400" />
                      {r.title}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
            {results.insights.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Intelligence">
                  {results.insights.map((i) => (
                    <CommandItem
                      key={i.id}
                      value={`ins ${i.title}`}
                      onSelect={() => go("/workspace")}
                    >
                      <Activity className="mr-2 h-4 w-4 text-violet-400" />
                      {i.title}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
            {results.entities.length > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Organizations">
                  {results.entities.map((e) => (
                    <CommandItem
                      key={e.id}
                      value={`ent ${e.name}`}
                      onSelect={() => go("/workspace")}
                    >
                      <Users className="mr-2 h-4 w-4 text-sky-400" />
                      {e.name}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
            {(results.competitors?.length ?? 0) > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Competitors">
                  {results.competitors!.map((c) => (
                    <CommandItem
                      key={c.id}
                      value={`comp ${c.name}`}
                      onSelect={() => go("/competitors")}
                    >
                      <Swords className="mr-2 h-4 w-4 text-fuchsia-400" />
                      {c.name}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
            {(results.monitoring?.length ?? 0) > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Monitoring">
                  {results.monitoring!.map((m) => (
                    <CommandItem
                      key={m.id}
                      value={`mon ${m.competitor} ${m.summary}`}
                      onSelect={() => go("/monitoring")}
                    >
                      <Radar className="mr-2 h-4 w-4 text-amber-400" />
                      <span className="truncate">
                        {m.competitor} · {m.category}
                      </span>
                      <span className="ml-auto text-[10px] text-muted-foreground">
                        {m.severity}
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
            {(results.leads?.length ?? 0) > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Leads">
                  {results.leads!.map((l) => (
                    <CommandItem
                      key={l.id}
                      value={`lead ${l.company}`}
                      onSelect={() => go("/lead-generation")}
                    >
                      <Target className="mr-2 h-4 w-4 text-emerald-400" />
                      <span className="truncate">{l.company}</span>
                      <span className="ml-auto text-[10px] text-muted-foreground">
                        {l.stage} · {l.score}
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
            {(results.website_audits?.length ?? 0) > 0 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Website audits">
                  {results.website_audits!.map((a) => (
                    <CommandItem
                      key={a.id}
                      value={`audit ${a.url}`}
                      onSelect={() => go("/website-audit")}
                    >
                      <Globe className="mr-2 h-4 w-4 text-violet-400" />
                      <span className="truncate">{a.url}</span>
                      {a.overall_score != null && (
                        <span className="ml-auto text-[10px] text-muted-foreground">
                          {a.overall_score}/100
                        </span>
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}
