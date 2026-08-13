import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "@tanstack/react-router";
import { companyService } from "@/services";
import type { Company, SessionUser, UserRole } from "@/services/types";

const STORAGE_KEY = "eaawp.session";

interface SessionState {
  user: SessionUser | null;
  hydrated: boolean;
  company: Company | null;
  signIn: (user: SessionUser) => void;
  signOut: () => void;
  selectCompany: (companyId: string) => void;
  setRole: (role: UserRole) => void;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
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
      company: user?.companyId ? (companyService.get(user.companyId) ?? null) : null,
      signIn: (u) => persist(u),
      signOut: () => persist(null),
      selectCompany: (companyId) => user && persist({ ...user, companyId }),
      setRole: (role) => user && persist({ ...user, role }),
    }),
    [user, hydrated, persist],
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
