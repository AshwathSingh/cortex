import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  forgetPendingWorkspaceDeletion,
  getPendingWorkspaceDeletions,
  rememberPendingWorkspaceDeletion,
} from "@/lib/workspace-delete-recovery";

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("workspace deletion recovery", () => {
  it("persists pending deletions per user and replaces duplicate workspace records", () => {
    expect(
      rememberPendingWorkspaceDeletion("user-1", {
        workspaceId: "workspace-1",
        workspaceName: "Original name",
      }),
    ).toBe(true);
    rememberPendingWorkspaceDeletion("user-1", {
      workspaceId: "workspace-1",
      workspaceName: "Current name",
    });

    expect(getPendingWorkspaceDeletions("user-1")).toEqual([
      { workspaceId: "workspace-1", workspaceName: "Current name" },
    ]);
    expect(getPendingWorkspaceDeletions("user-2")).toEqual([]);
  });

  it("removes only the completed deletion", () => {
    rememberPendingWorkspaceDeletion("user-1", {
      workspaceId: "workspace-1",
      workspaceName: "First",
    });
    rememberPendingWorkspaceDeletion("user-1", {
      workspaceId: "workspace-2",
      workspaceName: "Second",
    });

    forgetPendingWorkspaceDeletion("user-1", "workspace-1");

    expect(getPendingWorkspaceDeletions("user-1")).toEqual([
      { workspaceId: "workspace-2", workspaceName: "Second" },
    ]);
  });

  it("ignores malformed stored data", () => {
    window.localStorage.setItem(
      "cortex:pending-workspace-deletions:user-1",
      "not-json",
    );

    expect(getPendingWorkspaceDeletions("user-1")).toEqual([]);
  });

  it("reports when browser storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });

    expect(
      rememberPendingWorkspaceDeletion("user-1", {
        workspaceId: "workspace-1",
        workspaceName: "Workspace",
      }),
    ).toBe(false);
  });
});
