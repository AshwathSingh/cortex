import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspaceMemberList } from "@/components/workspaces/workspace-member-list";

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
];

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("WorkspaceMemberList", () => {
  it("shows active members, roles, and the current user", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(MEMBERS));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WorkspaceMemberList workspaceId="workspace-1" currentUserId="user-1" />,
    );

    expect(await screen.findByText("Ashwath Singh")).toBeInTheDocument();
    expect(screen.getByText("teammate@example.com")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("2 active members")).toBeInTheDocument();
    expect(screen.getByLabelText("Workspace members")).toBeInTheDocument();
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

    render(<WorkspaceMemberList workspaceId="workspace-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Members are unavailable",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Ashwath Singh")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
