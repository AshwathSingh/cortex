import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { hasAuthenticatedSession, redirectAuthenticatedUser } from "@/lib/server-auth";

const { cookieStore, cookiesMock, redirectMock } = vi.hoisted(() => ({
  cookieStore: { toString: vi.fn() },
  cookiesMock: vi.fn(),
  redirectMock: vi.fn(),
}));

vi.mock("next/headers", () => ({ cookies: cookiesMock }));
vi.mock("next/navigation", () => ({ redirect: redirectMock }));

beforeEach(() => {
  cookieStore.toString.mockReturnValue("cortex_session=session-token");
  cookiesMock.mockResolvedValue(cookieStore);
  redirectMock.mockClear();
});

afterEach(() => vi.unstubAllGlobals());

describe("server authentication redirect", () => {
  it("validates the browser cookie with the backend", async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchFn);
    expect(await hasAuthenticatedSession()).toBe(true);
    expect(fetchFn).toHaveBeenCalledWith(
      "http://localhost:8000/api/auth/me",
      expect.objectContaining({ headers: { cookie: "cortex_session=session-token" }, cache: "no-store" }),
    );
  });

  it("redirects a signed-in user into the workspace flow", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
    await redirectAuthenticatedUser();
    expect(redirectMock).toHaveBeenCalledWith("/workspaces");
  });

  it("keeps anonymous users on the requested public page", async () => {
    cookieStore.toString.mockReturnValue("");
    const fetchFn = vi.fn();
    vi.stubGlobal("fetch", fetchFn);
    expect(await hasAuthenticatedSession()).toBe(false);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("does not redirect for an expired session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    await redirectAuthenticatedUser();
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("leaves the page available when the backend cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    expect(await hasAuthenticatedSession()).toBe(false);
  });
});
