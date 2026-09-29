import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceSelector } from "@/components/workspaces/workspace-selector";
import type { AuthenticatedUser, WorkspaceSummary } from "@/lib/api-types";
import { rememberLastWorkspace } from "@/lib/last-workspace";

const router = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const USER: AuthenticatedUser = {
  id: "user-1",
  email: "developer@example.com",
  display_name: "Developer",
};

const WORKSPACES: WorkspaceSummary[] = [
  {
    id: "workspace-1",
    name: "First workspace",
    description: null,
    role: "OWNER",
    created_at: "2026-09-24T00:00:00Z",
  },
  {
    id: "workspace-2",
    name: "Previous workspace",
    description: null,
    role: "EDITOR",
    created_at: "2026-09-25T00:00:00Z",
  },
];

function mockWorkspaceRequests(workspaces = WORKSPACES) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const body = String(input).endsWith("/api/auth/me") ? USER : workspaces;
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

beforeEach(() => {
  router.replace.mockReset();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/workspaces");
});

afterEach(() => vi.unstubAllGlobals());

describe("WorkspaceSelector", () => {
  it("resumes the last accessible workspace", async () => {
    rememberLastWorkspace(USER.id, WORKSPACES[1].id);
    mockWorkspaceRequests();

    render(<WorkspaceSelector />);

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/workspaces/workspace-2"),
    );
  });

  it("opens a user's only workspace when no history exists", async () => {
    mockWorkspaceRequests([WORKSPACES[0]]);

    render(<WorkspaceSelector />);

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/workspaces/workspace-1"),
    );
  });

  it("shows the chooser when workspace selection was requested", async () => {
    window.history.replaceState({}, "", "/workspaces?select=1");
    rememberLastWorkspace(USER.id, WORKSPACES[1].id);
    mockWorkspaceRequests();

    render(<WorkspaceSelector />);

    expect(
      await screen.findByRole("heading", { name: "Choose a workspace" }),
    ).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.getByText("Previous workspace")).toBeInTheDocument();
  });
});
