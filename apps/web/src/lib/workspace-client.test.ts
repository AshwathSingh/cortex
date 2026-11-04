import { afterEach, describe, expect, it, vi } from "vitest";

import { updateWorkspaceProfile } from "@/lib/workspace-client";

afterEach(() => vi.unstubAllGlobals());

describe("workspace client", () => {
  it("updates the workspace profile with PATCH", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateWorkspaceProfile("workspace/one", {
      name: "Cortex Platform",
      description: "Project memory",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workspaces/workspace%2Fone",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          name: "Cortex Platform",
          description: "Project memory",
        }),
      }),
    );
  });
});
