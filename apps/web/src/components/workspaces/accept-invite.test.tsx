import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AcceptInvite } from "@/components/workspaces/accept-invite";
import { postAuthDestination } from "@/lib/invite-link";

const USER = {
  id: "user-1",
  email: "invitee@example.com",
  display_name: "Invitee",
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/invites/accept");
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("AcceptInvite", () => {
  it("accepts the captured token and opens the joined workspace", async () => {
    const user = userEvent.setup();
    window.history.replaceState(
      {},
      "",
      "/invites/accept#token=one-time-secret",
    );
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      !init?.method && String(input).endsWith("/auth/me")
        ? jsonResponse(USER)
        : jsonResponse({ workspace_id: "workspace-1", role: "EDITOR" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<AcceptInvite />);

    await user.click(
      await screen.findByRole("button", { name: "Accept invitation" }),
    );

    expect(
      await screen.findByRole("heading", { name: "You joined the workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open workspace" })).toHaveAttribute(
      "href",
      "/workspaces/workspace-1",
    );
    const acceptRequest = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/invites/accept"),
    );
    expect(JSON.parse(acceptRequest?.[1]?.body as string)).toEqual({
      token: "one-time-secret",
    });
    expect(window.location.hash).toBe("");
    expect(postAuthDestination()).toBe("/workspaces");
  });

  it("keeps the invite pending while a signed-out user authenticates", async () => {
    window.history.replaceState(
      {},
      "",
      "/invites/accept#token=one-time-secret",
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        jsonResponse({ detail: "Not authenticated" }, 401),
      ),
    );

    render(<AcceptInvite />);

    expect(
      await screen.findByRole("heading", { name: "Join a Cortex workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Log in to accept" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute(
      "href",
      "/signup",
    );
    expect(postAuthDestination()).toBe("/invites/accept");
  });

  it("shows an expired-invite error without losing the token", async () => {
    const user = userEvent.setup();
    window.history.replaceState(
      {},
      "",
      "/invites/accept#token=expired-secret",
    );
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => jsonResponse(USER))
      .mockImplementationOnce(() =>
        jsonResponse(
          { detail: "This invitation has expired; ask for a new one" },
          410,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<AcceptInvite />);
    await user.click(
      await screen.findByRole("button", { name: "Accept invitation" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This invitation has expired",
    );
    expect(postAuthDestination()).toBe("/invites/accept");
  });

  it("does not call the API when the link has no token", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<AcceptInvite />);

    expect(
      await screen.findByRole("heading", { name: "Invitation link missing" }),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
