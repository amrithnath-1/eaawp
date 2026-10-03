import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "@tanstack/react-router";
import { companyService } from "@/services";
import type { Company, SessionUser } from "@/services/types";
import { apiClient, USE_REAL_API } from "@/lib/api-client";

const STORAGE_KEY = "eaawp.session";

interface SessionState {
  user: SessionUser | null;
  hydrated: boolean;
  company: Company | null;
  signIn: (user: SessionUser) => void;
  signOut: () => void;
  selectCompany: (companyId: string) => void;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [company, setCompany] = useState<Company | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setUser(JSON.parse(raw) as SessionUser);
    } catch {
      /* ignore */
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    let active = true;
    if (!user?.companyId) {
      setCompany(null);
      return () => { active = false; };
    }
    if (!USE_REAL_API) {
      setCompany(companyService.get(user.companyId));
      return () => { active = false; };
    }
    void apiClient.get<{ id: string; name: string; industry?: string; region?: string; employees?: number }>(`/api/v1/companies/${encodeURIComponent(user.companyId)}`)
      .then((record) => {
        if (!active) return;
        setCompany({
          id: record.id,
          name: record.name,
          industry: record.industry ?? "",
          region: record.region ?? "",
          employees: record.employees ?? 0,
          agentRole: "Digital Marketing Manager",
          agentName: "Digital Marketing Manager",
        });
      })
      .catch(() => {
        if (!active) return;
        setCompany({
          id: user.companyId,
          name: "Company details unavailable",
          industry: "",
          region: "",
          employees: 0,
          agentRole: "Digital Marketing Manager",
          agentName: "Digital Marketing Manager",
        });
      });
    return () => { active = false; };
  }, [user?.companyId]);

  const persist = useCallback((next: SessionUser | null) => {
    setUser(next);
    try {
      if (next) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo<SessionState>(
    () => ({
      user,
      hydrated,
      company,
      signIn: (u) => persist(u),
      signOut: () => {
        persist(null);
        // Clear JWT tokens on sign out
        try {
          window.localStorage.removeItem("eaawp.access_token");
          window.localStorage.removeItem("eaawp.refresh_token");
        } catch { /* ignore */ }
      },
      selectCompany: (companyId) => user && persist({ ...user, companyId }),
    }),
    [user, hydrated, persist, company],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}

/** Redirects to login / company selection when the session is incomplete. */
export function useWorkspaceGuard() {
  const { user, hydrated, company } = useSession();
  const navigate = useNavigate();

  useEffect(() => {
    if (!hydrated) return;
    if (!user) navigate({ to: "/", replace: true });
    else if (!user.companyId) navigate({ to: "/company", replace: true });
  }, [hydrated, user, navigate]);

  return { ready: hydrated && !!user && !!company, user, company };
}
