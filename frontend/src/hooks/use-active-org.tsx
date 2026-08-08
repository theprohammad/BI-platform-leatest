import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchOrganizations, type Organization } from "@/services/intelligence";

/**
 * ActiveOrg is the backbone of the "one Intelligence Graph" experience.
 *
 * Instead of each page holding its own ephemeral analysis result (the old
 * sessionStorage approach, which vanished on refresh and left pages showing
 * "Run analysis" even after analysis completed), every page reads the SAME
 * active organization id from here and loads persisted graph data for it.
 *
 * The selected org id is persisted to localStorage so it survives refreshes and
 * new sessions. It defaults to the most recently created twin.
 */

const STORAGE_KEY = "sentient.activeOrg";

interface ActiveOrgValue {
  activeOrgId: string | null;
  setActiveOrgId: (id: string | null) => void;
  organizations: Organization[];
  activeOrg: Organization | null;
  isLoading: boolean;
  hasOrganizations: boolean;
}

const ActiveOrgContext = createContext<ActiveOrgValue | null>(null);

function loadStored(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function ActiveOrgProvider({ children }: { children: ReactNode }) {
  const [stored, setStored] = useState<string | null>(loadStored);

  const { data: organizations = [], isLoading } = useQuery({
    queryKey: ["organizations"],
    queryFn: fetchOrganizations,
    staleTime: 30_000,
  });

  // Resolve the effective active org: stored if still valid, else newest.
  const activeOrgId = useMemo(() => {
    if (organizations.length === 0) return null;
    if (stored && organizations.some((o) => o.id === stored)) return stored;
    return organizations[0]?.id ?? null; // list is newest-first from the API
  }, [stored, organizations]);

  // Persist whenever the effective id changes (e.g. auto-selected newest).
  useEffect(() => {
    if (!activeOrgId) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, activeOrgId);
    } catch {
      /* ignore quota */
    }
  }, [activeOrgId]);

  const setActiveOrgId = (id: string | null) => {
    setStored(id);
    try {
      if (id) window.localStorage.setItem(STORAGE_KEY, id);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  };

  const activeOrg = useMemo(
    () => organizations.find((o) => o.id === activeOrgId) ?? null,
    [organizations, activeOrgId],
  );

  const value: ActiveOrgValue = {
    activeOrgId,
    setActiveOrgId,
    organizations,
    activeOrg,
    isLoading,
    hasOrganizations: organizations.length > 0,
  };

  return <ActiveOrgContext.Provider value={value}>{children}</ActiveOrgContext.Provider>;
}

export function useActiveOrg() {
  const ctx = useContext(ActiveOrgContext);
  if (!ctx) throw new Error("useActiveOrg must be used within ActiveOrgProvider");
  return ctx;
}
