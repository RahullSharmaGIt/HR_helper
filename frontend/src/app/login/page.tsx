"use client";

import React, { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useSession } from "@/components/SessionProvider";
import { ApiClientError } from "@/lib/api";

function LoginForm() {
  const searchParams = useSearchParams();
  const isExpired = searchParams.get("expired") === "1";
  const { login } = useSession();

  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setLoading(true);

    try {
      await login(password);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        if (err.status === 429) {
          setErrorMessage("Too many failed login attempts. Please wait 5 minutes before trying again.");
        } else if (err.status === 401) {
          setErrorMessage("Invalid administrative password.");
        } else {
          setErrorMessage(err.message || "An authentication error occurred.");
        }
      } else {
        setErrorMessage("Network error connecting to the authentication service.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 p-4">
      <div className="max-w-md w-full bg-white rounded-lg shadow-sm border border-slate-200 p-8">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Review Platform Admin
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Evidence-based resume project review for hiring managers
          </p>
        </div>

        {isExpired && (
          <div
            role="alert"
            className="mb-5 p-3 rounded-md bg-amber-50 border border-amber-200 text-amber-800 text-sm font-medium"
          >
            Your session has expired. Please sign in again.
          </div>
        )}

        {errorMessage && (
          <div
            role="alert"
            className="mb-5 p-3 rounded-md bg-red-50 border border-red-200 text-red-700 text-sm"
          >
            {errorMessage}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="admin-password"
              className="block text-sm font-medium text-slate-700 mb-1"
            >
              Administrator Password
            </label>
            <input
              id="admin-password"
              type="password"
              name="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={loading}
              autoComplete="current-password"
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-md shadow-sm text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:outline-none disabled:bg-slate-50"
              placeholder="Enter admin password"
            />
          </div>

          <button
            type="submit"
            disabled={loading || !password}
            aria-busy={loading}
            className="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm rounded-md shadow-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <svg
                  className="animate-spin h-4 w-4 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v8H4z"
                  />
                </svg>
                Signing In...
              </>
            ) : (
              "Sign In"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-sm text-slate-500">Loading sign in...</div>}>
      <LoginForm />
    </Suspense>
  );
}
