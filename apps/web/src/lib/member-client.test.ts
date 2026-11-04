import { afterEach, describe, expect, it, vi } from "vitest";

import {
  listWorkspaceMembers,
  removeWorkspaceMember,
  updateWorkspaceMemberRole,
} from "@/lib/member-client";

afterEach(() => vi.unstubAllGlobals());

describe("member client", () => {
  it("loads members without exposing the workspace id as a query value", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listWorkspaceMembers("workspace/one");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workspaces/workspace%2Fone/members",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("updates a member role with a PATCH body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateWorkspaceMemberRole("workspace-1", "user/2", {
      role: "VIEWER",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workspaces/workspace-1/members/user%2F2/role",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ role: "VIEWER" }),
      }),
    );
  });

  it("removes a member with DELETE", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await removeWorkspaceMember("workspace-1", "user-2");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workspaces/workspace-1/members/user-2",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
