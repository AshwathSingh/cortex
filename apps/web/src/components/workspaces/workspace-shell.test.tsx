import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const OTHER_WORKSPACE = {
  ...WORKSPACE,
  id: "workspace-2",
  name: "Platform",
  role: "EDITOR",
} satisfies WorkspaceSummary;

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
    if (path === "/api/workspaces") {
      const body = workspaceStatus === 200 ? [workspaceBody, OTHER_WORKSPACE] : workspaceBody;
      return jsonResponse(workspaceStatus, body);
    }
    return jsonResponse(200, USER);
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
        ([input]) => String(input) === "/api/workspaces",
      ),
    ).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(
      screen.getByRole("link", { name: `Account: ${USER.display_name}` }),
    ).toHaveAttribute("href", `/workspaces/${WORKSPACE.id}/account`);
    expect(screen.getByRole("button", { name: `Switch workspace. Current workspace: ${WORKSPACE.name}` })).toBeInTheDocument();
  });

  it("opens workspace creation from the sidebar with a return destination", async () => {
    mockWorkspaceRequests();
    const user = userEvent.setup();

    render(
      <WorkspaceShell workspaceId={WORKSPACE.id}>
        <WorkspaceDetail workspaceId={WORKSPACE.id} />
      </WorkspaceShell>,
    );

    await user.click(
      await screen.findByRole("button", {
        name: `Switch workspace. Current workspace: ${WORKSPACE.name}`,
      }),
    );

    expect(screen.getByRole("link", { name: /new workspace/i })).toHaveAttribute(
      "href",
      `/workspaces/new?from=${WORKSPACE.id}`,
    );
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
