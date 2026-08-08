/** Investigation Template selector — choose an investigation type and see what it covers. */
import { useQuery } from "@tanstack/react-query";
import { Check, Loader2, Users } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchPlaybooks } from "@/services/intelligence";
import { cn } from "@/lib/utils";

export function PlaybookSelector({
  selected,
  onSelect,
}: {
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const {
    data: playbooks,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["playbooks"],
    queryFn: fetchPlaybooks,
  });

  if (isError) {
    return <p className="py-6 text-center text-sm text-rose-400">Couldn't load playbooks.</p>;
  }
  if (isLoading || !playbooks) {
    return (
      <div className="flex justify-center py-6">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {playbooks.map((pb) => {
        const active = selected === pb.id;
        return (
          <Card
            key={pb.id}
            onClick={() => onSelect(pb.id)}
            className={cn(
              "cursor-pointer p-4 transition-colors hover:border-violet-500/50",
              active && "border-violet-500 bg-violet-500/5",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium capitalize">{pb.id.replace(/_/g, " ")}</span>
              {active && <Check className="h-4 w-4 text-violet-400" />}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{pb.description}</p>
            <div className="mt-3 flex flex-wrap gap-1">
              {pb.specialists.map((s) => (
                <Badge key={s} variant="secondary" className="gap-1 text-[10px]">
                  <Users className="h-2.5 w-2.5" />
                  {s.replace(/_specialist$/, "").replace(/_/g, " ")}
                </Badge>
              ))}
            </div>
            <p className="mt-2 text-[10px] text-muted-foreground">v{pb.version}</p>
          </Card>
        );
      })}
    </div>
  );
}
