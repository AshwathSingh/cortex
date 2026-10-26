import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceDetail } from "@/components/workspaces/workspace-detail";
import {
  WorkspaceProvider,
  type WorkspaceContextValue,
} from "@/components/workspaces/workspace-context";
import type { WorkspaceSummary } from "@/lib/api-types";

const WORKSPACE = {
  id: "workspace-1",
  name: "Cortex Engineering",
  description: null,
  role: "OWNER",
  created_at: "2026-09-28T00:00:00Z",
} satisfies WorkspaceSummary;

function renderWorkspaceDetail(
  overrides: Partial<WorkspaceContextValue> = {},
) {
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
      <WorkspaceDetail workspaceId={WORKSPACE.id} />
    </WorkspaceProvider>,
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("WorkspaceDetail", () => {
  it("renders the shared workspace in the Cortex composer", () => {
    renderWorkspaceDetail();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      WORKSPACE.name,
    );
    expect(screen.getByText(`Workspace · ${WORKSPACE.name}`)).toBeInTheDocument();
    expect(screen.getByLabelText(/ask cortex about this workspace/i)).toBeEnabled();
    expect(screen.getByRole("button", { name: /send question/i })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("uses a different heading when the home view is remounted", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);

    const firstPage = renderWorkspaceDetail();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "What should we explore in",
    );
    await vi.waitFor(() =>
      expect(
        window.sessionStorage.getItem(`cortex:home-heading:${WORKSPACE.id}`),
      ).toBe("0"),
    );
    firstPage.unmount();

    renderWorkspaceDetail();
    await vi.waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
        "What would you like to understand about",
      ),
    );
  });

  it("places a suggested question into the composer", async () => {
    const user = userEvent.setup();
    renderWorkspaceDetail();

    await user.click(
      screen.getByRole("button", { name: "Show open contradictions" }),
    );

    expect(screen.getByLabelText(/ask cortex about this workspace/i)).toHaveValue(
      "Show open contradictions",
    );
    expect(screen.getByRole("button", { name: /send question/i })).toHaveAttribute(
      "aria-disabled",
      "false",
    );
  });

  it("adds the user question and a placeholder assistant response", async () => {
    const user = userEvent.setup();
    renderWorkspaceDetail();

    await user.type(
      screen.getByLabelText(/ask cortex about this workspace/i),
      "Why Neo4j?",
    );
    await user.click(screen.getByRole("button", { name: /send question/i }));

    expect(screen.getByLabelText("Conversation history")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "You" })).toHaveTextContent(
      "Why Neo4j?",
    );
    expect(screen.getByRole("article", { name: "Cortex" })).toHaveTextContent(
      /placeholder response from Cortex/i,
    );
    expect(screen.getByLabelText(/ask cortex about this workspace/i)).toHaveValue(
      "",
    );
  });

  it("keeps earlier messages when a follow-up question is submitted", async () => {
    const user = userEvent.setup();
    renderWorkspaceDetail();
    const input = screen.getByLabelText(/ask cortex about this workspace/i);

    await user.type(input, "Why Neo4j?");
    await user.click(screen.getByRole("button", { name: /send question/i }));
    await user.type(input, "What data is stored there?");
    await user.click(screen.getByRole("button", { name: /send question/i }));

    const messages = screen.getAllByRole("article");
    expect(messages).toHaveLength(4);
    expect(messages[0]).toHaveTextContent("Why Neo4j?");
    expect(messages[1]).toHaveAccessibleName("Cortex");
    expect(messages[2]).toHaveTextContent("What data is stored there?");
    expect(messages[3]).toHaveAccessibleName("Cortex");
  });
});
