"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  getCsrfToken,
  getSession,
  login as apiLogin,
  logout as apiLogout,
  setCsrfToken,
  setOnUnauthorized,
} from "@/lib/api";

interface SessionContextValue {
  isAuthenticated: boolean;
  csrfToken: string | null;
  isExpired: boolean;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
  dismissExpiredNotification: () => void;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [csrfToken, setCsrfTokenState] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isExpired, setIsExpired] = useState<boolean>(false);

  useEffect(() => {
    // Check initial session token in storage or verify cookie session
    const token = getCsrfToken();
    if (token) {
      setCsrfTokenState(token);
      setIsAuthenticated(true);
    } else {
      getSession()
        .then((s) => {
          if (s.csrfToken) {
            setCsrfTokenState(s.csrfToken);
            setIsAuthenticated(true);
          }
        })
        .catch(() => {
          // not logged in yet
        });
    }

    setOnUnauthorized(() => {
      setIsAuthenticated(false);
      setIsExpired(true);
      setCsrfToken(null);
      setCsrfTokenState(null);
      if (pathname && pathname !== "/login") {
        router.push("/login?expired=1");
      }
    });

    return () => {
      setOnUnauthorized(null);
    };
  }, [router, pathname]);

  const login = useCallback(
    async (password: string) => {
      const res = await apiLogin(password);
      setCsrfTokenState(res.csrfToken);
      setIsAuthenticated(true);
      setIsExpired(false);
      router.push("/");
    },
    [router]
  );

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setCsrfTokenState(null);
      setIsAuthenticated(false);
      router.push("/login");
    }
  }, [router]);

  const dismissExpiredNotification = useCallback(() => {
    setIsExpired(false);
  }, []);

  return (
    <SessionContext.Provider
      value={{
        isAuthenticated,
        csrfToken,
        isExpired,
        login,
        logout,
        dismissExpiredNotification,
      }}
    >
      {isExpired && pathname !== "/login" && (
        <div
          role="alert"
          aria-live="assertive"
          className="bg-amber-600 text-white px-4 py-2.5 text-center text-sm font-medium flex items-center justify-between shadow-md"
        >
          <span>Your administrative session has expired. Please sign in again.</span>
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/login?expired=1")}
              className="underline font-semibold hover:text-amber-100"
            >
              Sign In
            </button>
            <button
              onClick={dismissExpiredNotification}
              className="text-white/80 hover:text-white text-xs px-2 py-0.5 border border-white/40 rounded"
              aria-label="Dismiss alert"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return context;
}
