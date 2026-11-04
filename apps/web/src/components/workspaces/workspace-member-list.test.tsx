import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceMemberList } from "@/components/workspaces/workspace-member-list";
import type { WorkspaceMember } from "@/lib/api-types";

const MEMBERS = [
  {
    user_id: "user-1",
    name: "Ashwath Singh",
    email: "ashwath@example.com",
    role: "OWNER",
    role_id: null,
    permissions: [
      "sources.write",
      "members.manage",
      "roles.manage",
      "workspace.delete",
    ],
    created_at: "2026-09-28T00:00:00Z",
  },
  {
    user_id: "user-2",
    name: null,
    email: "teammate@example.com",
    role: "EDITOR",
    role_id: null,
    permissions: ["sources.write"],
    created_at: "2026-11-03T00:00:00Z",
  },
] satisfies WorkspaceMember[];

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ROLES = [
  {
    id: null,
    name: "OWNER",
    description: null,
    permissions: [
      "sources.write",
      "members.manage",
      "roles.manage",
      "workspace.delete",
    ],
    built_in: true,
    member_count: 1,
  },
  {
    id: null,
    name: "EDITOR",
    description: null,
    permissions: ["sources.write"],
    built_in: true,
    member_count: 1,
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

afterEach(() => vi.unstubAllGlobals());

describe("WorkspaceMemberList", () => {
  it("shows active members, roles, and the current user", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(MEMBERS));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WorkspaceMemberList
        workspaceId="workspace-1"
        currentUserId="user-1"
        currentRole="OWNER"
        permissions={MEMBERS[0].permissions}
        action={<button type="button">Invite member</button>}
      />,
    );

    expect(await screen.findByText("Ashwath Singh")).toBeInTheDocument();
    expect(screen.getByText("teammate@example.com")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Workspace members" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Invite member" })).toBeEnabled();
    expect(
      screen.getByRole("list", { name: "Workspace members" }),
    ).toHaveClass("overflow-y-auto");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workspaces/workspace-1/members",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("offers a retry when loading members fails", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ detail: "Members are unavailable" }, 503))
      .mockResolvedValueOnce(response(MEMBERS));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WorkspaceMemberList
        workspaceId="workspace-1"
        currentRole="VIEWER"
        permissions={[]}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Members are unavailable",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Ashwath Singh")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("opens member actions and updates a role", async () => {
    const user = userEvent.setup();
    const updatedMember = { ...MEMBERS[1], role: "VIEWER", permissions: [] };
    const fetchMock = vi.fn(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        if (path.endsWith("/roles")) return Promise.resolve(response(ROLES));
        if (init?.method === "PATCH") {
          return Promise.resolve(response(updatedMember));
        }
        return Promise.resolve(response(MEMBERS));
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WorkspaceMemberList
        workspaceId="workspace-1"
        currentUserId="user-1"
        currentRole="OWNER"
        permissions={MEMBERS[0].permissions}
      />,
    );

    const teammate = await screen.findByText("teammate@example.com");
    await user.click(teammate.closest("button") as HTMLButtonElement);
    await screen.findByRole("dialog");
    await user.selectOptions(screen.getByLabelText("Workspace role"), "builtin:VIEWER");
    await user.click(screen.getByRole("button", { name: "Save role" }));

    const roleRequest = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/members/user-2/role") &&
        init?.method === "PATCH",
    );
    expect(roleRequest).toBeDefined();
    expect(JSON.parse(roleRequest?.[1]?.body as string)).toEqual({
      role: "VIEWER",
    });
    expect(await screen.findByText("VIEWER")).toBeInTheDocument();
  });
});
