import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { onSessionExpired, refreshAccessToken, setAccessToken } from "../services/api";
import { auth } from "../services/endpoints";
import type { User } from "../types/api";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: Status;
  user: User | null;
  /** Set when we were signed out because the session ended (not by the user). */
  sessionExpired: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);

  const signOutLocally = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setStatus("anonymous");
    // Drop every cached server response so the next user never sees this one's data.
    queryClient.clear();
  }, [queryClient]);

  // Restore the session after a reload: the access token was only in memory, but the
  // HttpOnly refresh cookie (if any) can mint a new one.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const token = await refreshAccessToken();
      if (cancelled) return;
      if (!token) {
        setStatus("anonymous");
        return;
      }
      try {
        const me = await auth.me();
        if (!cancelled) {
          setUser(me);
          setStatus("authenticated");
        }
      } catch {
        if (!cancelled) signOutLocally();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [signOutLocally]);

  useEffect(() => {
    onSessionExpired(() => {
      setSessionExpired(true);
      signOutLocally();
    });
  }, [signOutLocally]);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await auth.login({ email, password });
    setAccessToken(tokens.access_token);
    const me = await auth.me();
    setUser(me);
    setSessionExpired(false);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await auth.logout(); // revokes the refresh session server-side
    } finally {
      setSessionExpired(false);
      signOutLocally();
    }
  }, [signOutLocally]);

  const value = useMemo(
    () => ({ status, user, sessionExpired, login, logout }),
    [status, user, sessionExpired, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
