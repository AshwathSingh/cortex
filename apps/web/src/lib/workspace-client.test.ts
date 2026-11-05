import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteWorkspace,
  updateWorkspaceProfile,
} from "@/lib/workspace-client";

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

  it("deletes a workspace with its exact confirmation name", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, { status: 204 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await deleteWorkspace("workspace/one", "Cortex Engineering");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workspaces/workspace%2Fone",
      expect.objectContaining({
        method: "DELETE",
        body: JSON.stringify({ confirm_name: "Cortex Engineering" }),
      }),
    );
  });
});
