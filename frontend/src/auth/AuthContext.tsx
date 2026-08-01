import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Redirect, useLocation } from "wouter";
import {
  ApiError,
  exchangeSession,
  getSession,
  login as loginRequest,
  logout as logoutRequest,
} from "../api/client";
import type { Session } from "../api/types";
import {
  beginCloudLogin,
  currentCloudAccessToken,
  resolveAuthMode,
  signOutCloud,
  subscribeToCloudSession,
} from "./supabase";

export type LoginResult = "SIGNED_IN" | "LINK_SENT";

interface AuthContextValue {
  session: Session | null;
  loading: boolean;
  login: (email: string) => Promise<LoginResult>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const cloudAuthEnabled = resolveAuthMode() === "cloud";

export function AuthProvider({ children }: PropsWithChildren) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setSession(await getSession());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        const token = cloudAuthEnabled ? await currentCloudAccessToken() : null;
        setSession(token ? await exchangeSession(token) : null);
      } else {
        throw error;
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh().catch(() => setSession(null));
  }, [refresh]);

  useEffect(() => {
    if (!cloudAuthEnabled) return undefined;
    return subscribeToCloudSession((supabaseSession) => {
      if (!supabaseSession?.access_token) {
        setSession(null);
        return;
      }
      void exchangeSession(supabaseSession.access_token)
        .then(setSession)
        .catch(() => setSession(null));
    });
  }, []);

  const login = useCallback(async (email: string) => {
    if (!cloudAuthEnabled) {
      setSession(await loginRequest(email));
      return "SIGNED_IN" as const;
    }
    const token = await beginCloudLogin(email);
    if (!token) return "LINK_SENT" as const;
    setSession(await exchangeSession(token));
    return "SIGNED_IN" as const;
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      try {
        if (cloudAuthEnabled) await signOutCloud();
      } finally {
        setSession(null);
      }
    }
  }, []);

  const value = useMemo(
    () => ({ session, loading, login, logout, refresh }),
    [session, loading, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}

export function PrivateRoute({ children }: PropsWithChildren) {
  const { session, loading } = useAuth();
  const [location] = useLocation();

  if (loading) {
    return (
      <main className="centered-state" aria-live="polite">
        <span className="spinner" aria-hidden="true" />
        <p>Verificando sesión segura…</p>
      </main>
    );
  }

  if (!session) {
    return <Redirect to="/login" replace state={{ from: location }} />;
  }

  return children;
}
