import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountSettings } from "@/components/account/account-settings";
import type { AuthenticatedUser } from "@/lib/api-types";

const { replace, refresh, routerMock } = vi.hoisted(() => {
  const replaceFn = vi.fn();
  const refreshFn = vi.fn();
  return {
    replace: replaceFn,
    refresh: refreshFn,
    routerMock: { replace: replaceFn, refresh: refreshFn, push: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

const USER: AuthenticatedUser = {
  id: "user-1",
  email: "engineer@example.com",
  display_name: "Cortex Engineer",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("AccountSettings", () => {
  it("shows the signed-in user's general account settings", () => {
    render(<AccountSettings user={USER} />);

    expect(screen.getByRole("heading", { name: "Your settings" })).toBeInTheDocument();
    expect(screen.getAllByText("Cortex Engineer").length).toBeGreaterThan(0);
    expect(screen.getAllByText("engineer@example.com").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Security" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Delete account" })).toBeInTheDocument();
  });

  it("does not imply unsupported account changes are available", () => {
    render(<AccountSettings user={USER} />);

    expect(screen.getByRole("button", { name: "Edit profile" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Change password" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete account" })).toBeDisabled();
  });

  it("signs the current session out", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<AccountSettings user={USER} />);

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/auth/logout",
        expect.objectContaining({ method: "POST", credentials: "same-origin" }),
      );
      expect(replace).toHaveBeenCalledWith("/login");
      expect(refresh).toHaveBeenCalled();
    });
  });
});
