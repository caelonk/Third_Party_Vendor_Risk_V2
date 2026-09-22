import { useQuery } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import type { Org } from "@/lib/types";
import { useAuth } from "@/auth/AuthProvider";

const STORAGE_KEY = "vr-org";

interface OrgContextValue {
  orgs: Org[];
  currentOrg: Org | null;
  setCurrentOrgId: (id: number) => void;
  loading: boolean;
}

const OrgContext = createContext<OrgContextValue | null>(null);

export function useOrgsQuery() {
  return useQuery({ queryKey: ["orgs"], queryFn: () => api.get<Org[]>("/orgs") });
}

export function OrgProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { data, isLoading } = useQuery({
    queryKey: ["orgs"],
    queryFn: () => api.get<Org[]>("/orgs"),
    enabled: !!user,
  });
  const orgs = useMemo(() => data ?? [], [data]);

  const [currentOrgId, setId] = useState<number | null>(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? Number(raw) : null;
  });

  useEffect(() => {
    if (orgs.length === 0) return;
    if (currentOrgId === null || !orgs.some((o) => o.id === currentOrgId)) {
      setId(orgs[0].id);
    }
  }, [orgs, currentOrgId]);

  const setCurrentOrgId = (id: number) => {
    setId(id);
    localStorage.setItem(STORAGE_KEY, String(id));
  };

  const currentOrg = orgs.find((o) => o.id === currentOrgId) ?? null;

  const value = useMemo(
    () => ({ orgs, currentOrg, setCurrentOrgId, loading: isLoading }),
    [orgs, currentOrg, isLoading],
  );
  return <OrgContext.Provider value={value}>{children}</OrgContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useOrg() {
  const ctx = useContext(OrgContext);
  if (!ctx) throw new Error("useOrg must be used within OrgProvider");
  return ctx;
}
