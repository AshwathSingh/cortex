import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  WorkspaceProvider,
  type WorkspaceContextValue,
} from "@/components/workspaces/workspace-context";
import { WorkspaceSettings } from "@/components/workspaces/workspace-settings";
import type { WorkspaceSummary } from "@/lib/api-types";
import {
  getPendingWorkspaceDeletions,
  rememberPendingWorkspaceDeletion,
} from "@/lib/workspace-delete-recovery";

const router = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const WORKSPACE = {
  id: "workspace-1",
  name: "Cortex Engineering",
  description: "Engineering project memory",
  role: "OWNER",
  permissions: [
    "sources.write",
    "members.manage",
    "roles.manage",
    "workspace.update",
    "workspace.delete",
  ],
  created_at: "2026-09-28T00:00:00Z",
} satisfies WorkspaceSummary;

const USER = {
  id: "user-1",
  email: "owner@example.com",
  display_name: "Workspace Owner",
};

const ROLES = [
  {
    id: null,
    name: "OWNER",
    description: null,
    permissions: WORKSPACE.permissions,
    built_in: true,
    member_count: 1,
  },
  {
    id: null,
    name: "EDITOR",
    description: null,
    permissions: ["sources.write"],
    built_in: true,
    member_count: 2,
  },
  {
    id: null,
    name: "VIEWER",
    description: null,
    permissions: [],
    built_in: true,
    member_count: 0,
  },
];

function renderSettings(overrides: Partial<WorkspaceContextValue> = {}) {
  return render(
    <WorkspaceProvider
      value={{
        workspaceId: WORKSPACE.id,
        workspace: WORKSPACE,
        user: USER,
        isLoading: false,
        error: null,
        ...overrides,
      }}
    >
      <WorkspaceSettings />
    </WorkspaceProvider>,
  );
}

beforeEach(() => {
  router.replace.mockReset();
  router.refresh.mockReset();
  window.localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value() {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value() {
      this.removeAttribute("open");
    },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("WorkspaceSettings", () => {
  it("shows the workspace's general identity and access settings", () => {
    renderSettings();

    expect(
      screen.getByRole("heading", { name: "Workspace settings" }),
    ).toHaveClass("sr-only");
    expect(screen.getByText(WORKSPACE.name)).toBeInTheDocument();
    expect(screen.getByText(WORKSPACE.description)).toBeInTheDocument();
    expect(screen.queryByText("Your access")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit details" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Invite member" })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Danger zone" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete workspace" })).toBeEnabled();
  });

  it("shows a leave action to non-owners", () => {
    renderSettings({
      workspace: { ...WORKSPACE, role: "VIEWER", permissions: [] },
    });

    expect(screen.getByRole("heading", { name: "Danger zone" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Leave workspace" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Invite member" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave workspace" })).toBeDisabled();
  });

  it("lets an owner edit the workspace name and description", async () => {
    const user = userEvent.setup();
    const updatedWorkspace = {
      ...WORKSPACE,
      name: "Cortex Platform",
      description: "Shared engineering memory",
    };
    const updateWorkspace = vi.fn();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            init?.method === "PATCH" ? updatedWorkspace : [],
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderSettings({ updateWorkspace });

    await user.click(screen.getByRole("button", { name: "Edit details" }));
    const nameInput = screen.getByLabelText("Workspace name");
    await user.clear(nameInput);
    await user.type(nameInput, "Cortex Platform");
    await user.clear(screen.getByLabelText("Description"));
    await user.type(
      screen.getByLabelText("Description"),
      "Shared engineering memory",
    );
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    const updateRequest = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/api/workspaces/workspace-1") &&
        init?.method === "PATCH",
    );
    expect(updateRequest).toBeDefined();
    expect(JSON.parse(updateRequest?.[1]?.body as string)).toEqual({
      name: "Cortex Platform",
      description: "Shared engineering memory",
    });
    expect(updateWorkspace).toHaveBeenCalledWith(updatedWorkspace);
  });

  it("lets custom member managers invite only roles they can grant", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              String(input).endsWith("/members")
                ? []
                : [
                    ...ROLES,
                    {
                      id: "role-1",
                      name: "Member manager",
                      description: "Coordinates workspace access",
                      permissions: ["members.manage"],
                      built_in: false,
                      member_count: 1,
                    },
                  ],
            ),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    );
    renderSettings({
      workspace: {
        ...WORKSPACE,
        role: "Team lead",
        permissions: ["members.manage"],
      },
    });

    await user.click(screen.getByRole("button", { name: "Invite member" }));

    expect(
      await screen.findByRole("option", { name: /Member manager/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Viewer/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Editor/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Owner/ })).not.toBeInTheDocument();
  });

  it("creates an invite with the selected workspace role", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const body = path.endsWith("/members")
        ? []
        : !init?.method && path.endsWith("/roles")
          ? ROLES
          : {
              id: "invite-1",
              email: "teammate@example.com",
              role: "EDITOR",
              role_id: null,
              expires_at: "2026-11-10T12:00:00Z",
              token: "one-time-secret",
            };
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: path.endsWith("/roles") || path.endsWith("/members") ? 200 : 201,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    renderSettings();

    await user.click(screen.getByRole("button", { name: "Invite member" }));
    await screen.findByRole("option", { name: /Editor/ });
    await user.type(
      screen.getByLabelText("Email address"),
      "teammate@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Create invite" }));

    expect(
      await screen.findByRole("heading", { name: "Invite created" }),
    ).toBeInTheDocument();
    const inviteRequest = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/invites"),
    );
    expect(inviteRequest).toBeDefined();
    expect(JSON.parse(inviteRequest?.[1]?.body as string)).toEqual({
      email: "teammate@example.com",
      role: "EDITOR",
    });
  });

  it("copies the stable workspace identifier", async () => {
    const user = userEvent.setup();
    const writeText = vi
      .spyOn(navigator.clipboard, "writeText")
      .mockResolvedValue(undefined);
    renderSettings();

    await user.click(screen.getByRole("button", { name: "Copy ID" }));

    expect(writeText).toHaveBeenCalledWith(WORKSPACE.id);
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("requires the exact workspace name before deletion", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(fetch);
    renderSettings();

    await user.click(screen.getByRole("button", { name: "Delete workspace" }));

    expect(
      screen.getByRole("heading", { name: `Delete ${WORKSPACE.name}?` }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/members, pending invites, connected sources, and graph data/i),
    ).toBeInTheDocument();
    const confirmation = screen.getByLabelText(
      `Type ${WORKSPACE.name} to confirm`,
    );
    const deleteButton = screen.getAllByRole("button", {
      name: "Delete workspace",
    })[1];

    expect(deleteButton).toBeDisabled();
    await user.type(confirmation, WORKSPACE.name.toLowerCase());
    expect(deleteButton).toBeDisabled();
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE"),
    ).toBe(false);

    await user.clear(confirmation);
    await user.type(confirmation, WORKSPACE.name);
    expect(deleteButton).toBeEnabled();
  });

  it("deletes the workspace, clears its resume state, and redirects", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      Promise.resolve(
        init?.method === "DELETE"
          ? new Response(null, { status: 204 })
          : new Response("[]", {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    rememberPendingWorkspaceDeletion(USER.id, {
      workspaceId: WORKSPACE.id,
      workspaceName: WORKSPACE.name,
    });
    window.localStorage.setItem("cortex:last-workspace:user-1", WORKSPACE.id);
    renderSettings({ user: USER });

    await user.click(screen.getByRole("button", { name: "Delete workspace" }));
    await user.type(
      screen.getByLabelText(`Type ${WORKSPACE.name} to confirm`),
      WORKSPACE.name,
    );
    await user.click(
      screen.getAllByRole("button", { name: "Delete workspace" })[1],
    );

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/workspaces"),
    );
    const deleteRequest = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "DELETE",
    );
    expect(deleteRequest?.[0]).toBe("/api/workspaces/workspace-1");
    expect(JSON.parse(deleteRequest?.[1]?.body as string)).toEqual({
      confirm_name: WORKSPACE.name,
    });
    expect(window.localStorage.getItem("cortex:last-workspace:user-1")).toBeNull();
    expect(getPendingWorkspaceDeletions(USER.id)).toEqual([]);
  });

  it("locks the modal while deletion is in progress", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        init?.method === "DELETE"
          ? new Promise<Response>(() => {})
          : Promise.resolve(
              new Response("[]", {
                status: 200,
                headers: { "Content-Type": "application/json" },
              }),
            ),
      ),
    );
    renderSettings();

    await user.click(screen.getByRole("button", { name: "Delete workspace" }));
    await user.type(
      screen.getByLabelText(`Type ${WORKSPACE.name} to confirm`),
      WORKSPACE.name,
    );
    await user.click(
      screen.getAllByRole("button", { name: "Delete workspace" })[1],
    );

    expect(
      screen.getByRole("button", { name: "Deleting workspace…" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(
      screen.getByLabelText(`Type ${WORKSPACE.name} to confirm`),
    ).toBeDisabled();
  });

  it.each([
    [400, "The workspace name may have changed"],
    [403, "Only the workspace owner can delete it"],
  ])("shows deletion feedback for a %i response", async (status, message) => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        Promise.resolve(
          init?.method === "DELETE"
            ? new Response(
                JSON.stringify({
                  detail: "The workspace could not be fully deleted",
                }),
                {
                  status,
                  headers: { "Content-Type": "application/json" },
                },
              )
            : new Response("[]", {
                status: 200,
                headers: { "Content-Type": "application/json" },
              }),
        ),
      ),
    );
    renderSettings();

    await user.click(screen.getByRole("button", { name: "Delete workspace" }));
    await user.type(
      screen.getByLabelText(`Type ${WORKSPACE.name} to confirm`),
      WORKSPACE.name,
    );
    await user.click(
      screen.getAllByRole("button", { name: "Delete workspace" })[1],
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(
      screen.getAllByRole("button", { name: "Delete workspace" })[1],
    ).toBeEnabled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("provides a sign-in action when the session expires", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        Promise.resolve(
          init?.method === "DELETE"
            ? new Response(JSON.stringify({ detail: "Not authenticated" }), {
                status: 401,
                headers: { "Content-Type": "application/json" },
              })
            : new Response("[]", {
                status: 200,
                headers: { "Content-Type": "application/json" },
              }),
        ),
      ),
    );
    renderSettings();

    await user.click(screen.getByRole("button", { name: "Delete workspace" }));
    await user.type(
      screen.getByLabelText(`Type ${WORKSPACE.name} to confirm`),
      WORKSPACE.name,
    );
    await user.click(
      screen.getAllByRole("button", { name: "Delete workspace" })[1],
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your session has expired",
    );
    expect(
      screen.getByLabelText(`Type ${WORKSPACE.name} to confirm`),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Sign in again" }));
    expect(router.replace).toHaveBeenCalledWith("/login");
  });

  it("persists interrupted cleanup and opens the recovery page", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        Promise.resolve(
          init?.method === "DELETE"
            ? new Response(
                JSON.stringify({
                  detail: "The workspace could not be fully deleted",
                }),
                {
                  status: 500,
                  headers: { "Content-Type": "application/json" },
                },
              )
            : new Response("[]", {
                status: 200,
                headers: { "Content-Type": "application/json" },
              }),
        ),
      ),
    );
    renderSettings();

    await user.click(screen.getByRole("button", { name: "Delete workspace" }));
    await user.type(
      screen.getByLabelText(`Type ${WORKSPACE.name} to confirm`),
      WORKSPACE.name,
    );
    await user.click(
      screen.getAllByRole("button", { name: "Delete workspace" })[1],
    );

    await vi.waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/workspaces"),
    );
    expect(getPendingWorkspaceDeletions(USER.id)).toEqual([
      { workspaceId: WORKSPACE.id, workspaceName: WORKSPACE.name },
    ]);
  });
});
