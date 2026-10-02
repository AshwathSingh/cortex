import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceDetail } from "@/components/workspaces/workspace-detail";
import { WorkspaceShell } from "@/components/workspaces/workspace-shell";
import type { AuthenticatedUser, WorkspaceSummary } from "@/lib/api-types";

const router = { replace: vi.fn() };
vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1",
  useRouter: () => router,
}));

const WORKSPACE = {
  id: "workspace-1",
  name: "Cortex Engineering",
  description: null,
  role: "OWNER",
  created_at: "2026-09-28T00:00:00Z",
} satisfies WorkspaceSummary;

const USER = {
  id: "user-1",
  email: "engineer@example.com",
  display_name: "Cortex Engineer",
} satisfies AuthenticatedUser;

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function mockWorkspaceRequests(workspaceStatus = 200, workspaceBody: unknown = WORKSPACE) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    return path === `/api/workspaces/${WORKSPACE.id}`
      ? jsonResponse(workspaceStatus, workspaceBody)
      : jsonResponse(200, USER);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  router.replace.mockReset();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("WorkspaceShell", () => {
  it("loads workspace data once and shares it with the home view", async () => {
    const fetchMock = mockWorkspaceRequests();

    render(
      <WorkspaceShell workspaceId={WORKSPACE.id}>
        <WorkspaceDetail workspaceId={WORKSPACE.id} />
      </WorkspaceShell>,
    );

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      WORKSPACE.name,
    );
    expect(
      fetchMock.mock.calls.filter(
        ([input]) => String(input) === `/api/workspaces/${WORKSPACE.id}`,
      ),
    ).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(
      screen.getByRole("link", { name: `Account: ${USER.display_name}` }),
    ).toHaveAttribute("href", `/workspaces/${WORKSPACE.id}/account`);
  });

  it("returns expired sessions to login", async () => {
    mockWorkspaceRequests(401, { detail: "Not authenticated" });

    render(
      <WorkspaceShell workspaceId={WORKSPACE.id}>
        <WorkspaceDetail workspaceId={WORKSPACE.id} />
      </WorkspaceShell>,
    );

    await vi.waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });

  it("shows workspace loading errors instead of rendering a child route", async () => {
    mockWorkspaceRequests(403, { detail: "Workspace access denied." });

    render(
      <WorkspaceShell workspaceId={WORKSPACE.id}>
        <WorkspaceDetail workspaceId={WORKSPACE.id} />
      </WorkspaceShell>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Workspace access denied.",
    );
    expect(screen.queryByLabelText("Ask Cortex")).not.toBeInTheDocument();
  });
});
