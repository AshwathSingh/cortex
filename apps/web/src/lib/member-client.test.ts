import { afterEach, describe, expect, it, vi } from "vitest";

import { listWorkspaceMembers } from "@/lib/member-client";

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
});
