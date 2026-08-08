/**
 * OrgPicker — the single control for choosing which organization every page is
 * viewing. Bound to ActiveOrg, so switching it here re-scopes the whole app to
 * that organization's slice of the Intelligence Graph.
 */
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useActiveOrg } from "@/hooks/use-active-org";

export function OrgPicker({ className }: { className?: string }) {
  const { activeOrgId, setActiveOrgId, organizations, hasOrganizations } = useActiveOrg();

  if (!hasOrganizations) return null;

  return (
    <Select value={activeOrgId ?? ""} onValueChange={(v) => setActiveOrgId(v)}>
      <SelectTrigger
        className={className ?? "w-56 rounded-xl border-[var(--hairline)] bg-[var(--surface)]/70"}
      >
        <SelectValue placeholder="Select organization…" />
      </SelectTrigger>
      <SelectContent>
        {organizations.map((o) => (
          <SelectItem key={o.id} value={o.id}>
            {o.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
