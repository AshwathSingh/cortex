import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  WorkspaceProvider,
  type WorkspaceContextValue,
} from "@/components/workspaces/workspace-context";
import { WorkspaceSettings } from "@/components/workspaces/workspace-settings";
import type { WorkspaceSummary } from "@/lib/api-types";

const WORKSPACE = {
  id: "workspace-1",
  name: "Cortex Engineering",
  description: "Engineering project memory",
  role: "OWNER",
  permissions: [
    "sources.write",
    "members.manage",
    "roles.manage",
    "workspace.delete",
  ],
  created_at: "2026-09-28T00:00:00Z",
} satisfies WorkspaceSummary;

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
        user: null,
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
    ).toBeInTheDocument();
    expect(screen.getByText(WORKSPACE.name)).toBeInTheDocument();
    expect(screen.getByText(WORKSPACE.description)).toBeInTheDocument();
    expect(screen.getByText("OWNER")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit details" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Invite member" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Delete workspace" })).toBeDisabled();
  });

  it("shows a leave action to non-owners", () => {
    renderSettings({
      workspace: { ...WORKSPACE, role: "VIEWER", permissions: [] },
    });

    expect(screen.getByRole("heading", { name: "Leave workspace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Invite member" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Leave workspace" })).toBeDisabled();
  });

  it("lets custom member managers invite only roles they can grant", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify([
            ...ROLES,
            {
              id: "role-1",
              name: "Member manager",
              description: "Coordinates workspace access",
              permissions: ["members.manage"],
              built_in: false,
              member_count: 1,
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
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

    expect(screen.getByText("Team lead")).toBeInTheDocument();
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
      const body = !init?.method && path.endsWith("/roles")
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
          status: path.endsWith("/roles") ? 200 : 201,
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
});
