import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createWorkspaceInvite,
  listWorkspaceRoles,
} from "@/lib/invite-client";

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("invite client", () => {
  it("loads the roles available in a workspace", async () => {
    const fetchMock = vi.fn().mockImplementation(() => jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    await listWorkspaceRoles("workspace/one");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workspaces/workspace%2Fone/roles",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("creates a built-in-role invite without putting the token in the URL", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      jsonResponse(
        {
          id: "invite-1",
          email: "teammate@example.com",
          role: "EDITOR",
          role_id: null,
          expires_at: "2026-11-10T12:00:00Z",
          token: "secret",
        },
        201,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createWorkspaceInvite("workspace-1", {
      email: "teammate@example.com",
      role: "EDITOR",
    });

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/workspaces/workspace-1/invites");
    expect(init).toEqual(
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
      }),
    );
    expect(JSON.parse(init.body)).toEqual({
      email: "teammate@example.com",
      role: "EDITOR",
    });
  });

  it("sends a custom role by id", async () => {
    const fetchMock = vi.fn().mockImplementation(() => jsonResponse({}, 201));
    vi.stubGlobal("fetch", fetchMock);

    await createWorkspaceInvite("workspace-1", {
      email: "teammate@example.com",
      role_id: "role-1",
    });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      email: "teammate@example.com",
      role_id: "role-1",
    });
  });
});
