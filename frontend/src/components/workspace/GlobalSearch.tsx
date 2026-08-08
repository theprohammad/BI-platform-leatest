/** Global search across entities, claims, insights, recommendations. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Search as SearchIcon } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ConfidenceMeter } from "@/components/premium/primitives";
import { searchWorkspace } from "@/services/intelligence";

export function GlobalSearch({
  orgId,
  onOpenClaim,
}: {
  orgId: string;
  onOpenClaim: (claimId: string) => void;
}) {
  const [q, setQ] = useState("");
  const enabled = q.trim().length >= 2;
  const { data, isFetching } = useQuery({
    queryKey: ["ws-search", orgId, q],
    queryFn: () => searchWorkspace(q, orgId),
    enabled,
  });

  return (
    <div className="space-y-4">
      <div className="relative">
        <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search entities, claims, insights, recommendations…"
          className="pl-9"
        />
        {isFetching && (
          <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground" />
        )}
      </div>

      {enabled && data && (
        <div className="space-y-4">
          <ResultGroup label="Organizations" count={data.entities.length}>
            {data.entities.map((e) => (
              <div key={e.id} className="rounded-md border p-2 text-sm">
                <span className="font-medium">{e.name}</span>
                <Badge variant="secondary" className="ml-2 text-[10px]">
                  {e.type}
                </Badge>
              </div>
            ))}
          </ResultGroup>
          <ResultGroup label="Recommendations" count={data.recommendations.length}>
            {data.recommendations.map((r) => (
              <div key={r.id} className="rounded-md border p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{r.title}</span>
                  <ConfidenceMeter value={r.trust?.confidence ?? 0} size="sm" />
                </div>
              </div>
            ))}
          </ResultGroup>
          <ResultGroup label="Intelligence" count={data.insights.length}>
            {data.insights.map((i) => (
              <div key={i.id} className="rounded-md border p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{i.title}</span>
                  <ConfidenceMeter value={i.trust?.confidence ?? 0} size="sm" />
                </div>
              </div>
            ))}
          </ResultGroup>
          <ResultGroup label="Findings" count={data.claims.length}>
            {data.claims.map((c) => (
              <button
                key={c.id}
                onClick={() => onOpenClaim(c.id)}
                className="flex w-full items-center justify-between gap-2 rounded-md border p-2 text-left hover:bg-muted/40"
              >
                <span className="text-sm">{c.statement}</span>
                <ConfidenceMeter value={c.trust?.confidence ?? 0} size="sm" />
              </button>
            ))}
          </ResultGroup>
        </div>
      )}
    </div>
  );
}

function ResultGroup({
  label,
  count,
  children,
}: {
  label: string;
  count: number;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label} ({count})
      </h4>
      <div className="space-y-2">{children}</div>
    </section>
  );
}
