import { createContext, useContext, useState, type ReactNode } from "react";
import type { AnalysisData, AnalysisRequest } from "@/services/api";

interface AnalysisEntry {
  request: AnalysisRequest;
  data: AnalysisData;
  completedAt: number;
}

interface AnalysisContextValue {
  latest: AnalysisEntry | null;
  setLatest: (entry: AnalysisEntry) => void;
  clear: () => void;
}

const AnalysisContext = createContext<AnalysisContextValue | null>(null);

const STORAGE_KEY = "sentient.analysis.latest";

function loadInitial(): AnalysisEntry | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AnalysisEntry) : null;
  } catch {
    return null;
  }
}

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [latest, setLatestState] = useState<AnalysisEntry | null>(loadInitial);

  const setLatest = (entry: AnalysisEntry) => {
    setLatestState(entry);
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entry));
    } catch {
      /* ignore quota errors */
    }
  };

  const clear = () => {
    setLatestState(null);
    try {
      window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  };

  return (
    <AnalysisContext.Provider value={{ latest, setLatest, clear }}>
      {children}
    </AnalysisContext.Provider>
  );
}

export function useAnalysis() {
  const ctx = useContext(AnalysisContext);
  if (!ctx) throw new Error("useAnalysis must be used within AnalysisProvider");
  return ctx;
}
