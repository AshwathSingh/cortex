import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  created_at: "2026-09-28T00:00:00Z",
} satisfies WorkspaceSummary;

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

afterEach(() => {
  vi.restoreAllMocks();
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
    expect(screen.getByRole("button", { name: "Manage members" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete workspace" })).toBeDisabled();
  });

  it("shows a leave action to non-owners", () => {
    renderSettings({
      workspace: { ...WORKSPACE, role: "VIEWER" },
    });

    expect(screen.getByRole("heading", { name: "Leave workspace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave workspace" })).toBeDisabled();
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
