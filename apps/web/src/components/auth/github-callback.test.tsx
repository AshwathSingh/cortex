import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GitHubCallback } from "@/components/auth/github-callback";
import { LoginForm } from "@/components/auth/login-form";
import { capturePendingInviteToken } from "@/lib/invite-link";

const router = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  router.replace.mockReset();
  router.refresh.mockReset();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/login");
});
afterEach(() => vi.unstubAllGlobals());

describe("GitHub login button", () => {
  it("navigates to the backend OAuth start endpoint", () => {
    render(<LoginForm />);
    const link = screen.getByRole("link", { name: /continue with github/i });
    expect(link).toHaveAttribute("href", "/api/auth/github/login");
  });

  it("returns an email login to its pending invitation", async () => {
    const user = userEvent.setup();
    window.history.replaceState(
      {},
      "",
      "/invites/accept#token=one-time-secret",
    );
    capturePendingInviteToken();
    mockFetch(200, {
      id: "u1",
      email: "invitee@example.com",
      display_name: "Invitee",
    });
    render(<LoginForm />);

    await user.type(screen.getByLabelText("Email"), "invitee@example.com");
    await user.type(screen.getByLabelText("Password"), "password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/invites/accept"),
    );
  });
});

describe("GitHubCallback", () => {
  it("relays code and state once, then opens the Workspace Selector", async () => {
    const fetchFn = mockFetch(200, {
      id: "u1",
      email: "octocat@example.com",
      display_name: "The Octocat",
    });

    render(
      <StrictMode>
        <GitHubCallback code="abc" state="xyz" error={null} />
      </StrictMode>,
    );

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/workspaces"),
    );
    // A GitHub code is single-use; StrictMode must not replay it.
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/auth/github/callback");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ code: "abc", state: "xyz" });
  });

  it("returns GitHub sign-in to a pending invitation", async () => {
    window.history.replaceState(
      {},
      "",
      "/invites/accept#token=one-time-secret",
    );
    capturePendingInviteToken();
    mockFetch(200, {
      id: "u1",
      email: "octocat@example.com",
      display_name: "The Octocat",
    });

    render(<GitHubCallback code="abc" state="xyz" error={null} />);

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/invites/accept"),
    );
  });

  it("shows the backend's reason and stays put when sign-in is rejected", async () => {
    mockFetch(401, { detail: "GitHub sign-in failed. Please try again." });

    render(<GitHubCallback code="abc" state="forged" error={null} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "GitHub sign-in failed. Please try again.",
    );
    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /back to log in/i })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  it("does not call the backend when the user cancels on GitHub", () => {
    const fetchFn = mockFetch(200, {});

    render(<GitHubCallback code={null} state="xyz" error="access_denied" />);

    expect(screen.getByRole("alert")).toHaveTextContent(/cancelled/i);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("does not call the backend when GitHub sent no code", () => {
    const fetchFn = mockFetch(200, {});

    render(<GitHubCallback code={null} state={null} error={null} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/failed/i);
    expect(fetchFn).not.toHaveBeenCalled();
  });
});
