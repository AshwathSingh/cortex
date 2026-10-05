import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GitHubCallback } from "@/components/auth/github-callback";
import { LoginForm } from "@/components/auth/login-form";

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
});
afterEach(() => vi.unstubAllGlobals());

describe("GitHub login button", () => {
  it("navigates to the backend OAuth start endpoint", () => {
    render(<LoginForm />);
    const link = screen.getByRole("link", { name: /continue with github/i });
    expect(link).toHaveAttribute("href", "/api/auth/github/login");
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
