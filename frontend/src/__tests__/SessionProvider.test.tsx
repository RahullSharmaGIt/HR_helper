import React from "react";
import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SessionProvider, useSession } from "../components/SessionProvider";
import * as api from "../lib/api";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
  usePathname: () => "/dashboard",
}));

function ConsumerComponent() {
  const { isAuthenticated, isExpired, logout } = useSession();
  return (
    <div>
      <div data-testid="auth-state">{isAuthenticated ? "logged-in" : "logged-out"}</div>
      <div data-testid="expired-state">{isExpired ? "expired" : "valid"}</div>
      <button onClick={() => logout()}>Logout</button>
    </div>
  );
}

describe("SessionProvider & Expired Sessions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it("handles expired sessions by notifying user and routing to login", async () => {
    let capturedUnauthorizedCallback: (() => void) | null = null;
    vi.spyOn(api, "setOnUnauthorized").mockImplementation((cb) => {
      capturedUnauthorizedCallback = cb;
    });

    render(
      <SessionProvider>
        <ConsumerComponent />
      </SessionProvider>
    );

    expect(screen.getByTestId("expired-state")).toHaveTextContent("valid");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    // Simulate backend returning 401 Unauthorized during active operation
    act(() => {
      if (capturedUnauthorizedCallback) {
        capturedUnauthorizedCallback();
      }
    });

    // Verify session marked expired
    expect(screen.getByTestId("expired-state")).toHaveTextContent("expired");
    expect(screen.getByTestId("auth-state")).toHaveTextContent("logged-out");

    // Verify accessible alert banner is displayed
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent(
      "Your administrative session has expired. Please sign in again."
    );

    // Verify redirect to /login?expired=1
    expect(mockPush).toHaveBeenCalledWith("/login?expired=1");
  });
});
