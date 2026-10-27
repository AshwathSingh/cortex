import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceDetail } from "@/components/workspaces/workspace-detail";
import {
  WorkspaceProvider,
  type WorkspaceContextValue,
} from "@/components/workspaces/workspace-context";
import type { AuthenticatedUser, WorkspaceSummary } from "@/lib/api-types";

const WORKSPACE = {
  id: "workspace-1",
  name: "Cortex Engineering",
  description: null,
  role: "OWNER",
  created_at: "2026-09-28T00:00:00Z",
} satisfies WorkspaceSummary;

const USER = {
  id: "user-1",
  email: "ash@example.com",
  display_name: "Ash Ketchum",
} satisfies AuthenticatedUser;

function renderWorkspaceDetail(
  overrides: Partial<WorkspaceContextValue> = {},
) {
  return render(
    <WorkspaceProvider
      value={{
        workspaceId: WORKSPACE.id,
        workspace: WORKSPACE,
        user: USER,
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
      "Graph-Aware Assistant",
    );
    expect(
      screen.getByRole("heading", { level: 2, name: new RegExp(WORKSPACE.name) }),
    ).toBeInTheDocument();
    expect(screen.getByText(`Workspace · ${WORKSPACE.name}`)).toBeInTheDocument();
    expect(screen.getByText(/trace project decisions/i)).toBeInTheDocument();
    const context = screen.getByRole("navigation", {
      name: "Available answer context",
    });
    expect(within(context).getByRole("link", { name: "Graph" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE.id}/graph`,
    );
    expect(within(context).getByRole("link", { name: "Sources" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE.id}/sources`,
    );
    expect(screen.getByLabelText(/ask cortex about this workspace/i)).toBeEnabled();
    expect(screen.getByRole("button", { name: /send question/i })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("uses a different heading when the home view is remounted", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);

    const firstPage = renderWorkspaceDetail();
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: /What should we explore in/,
      }),
    ).toBeInTheDocument();
    await vi.waitFor(() =>
      expect(
        window.sessionStorage.getItem(`cortex:home-heading:${WORKSPACE.id}`),
      ).toBe("0"),
    );
    firstPage.unmount();

    renderWorkspaceDetail();
    await vi.waitFor(() =>
      expect(
        screen.getByRole("heading", {
          level: 2,
          name: /What would you like to understand about/,
        }),
      ).toBeInTheDocument(),
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
    const turn = screen.getByRole("article", { name: "Conversation turn 1" });
    const userMessage = within(turn).getByRole("region", { name: "Your message" });
    expect(userMessage).toHaveTextContent(USER.display_name);
    expect(userMessage).toHaveTextContent("Why Neo4j?");
    expect(within(turn).getByRole("region", { name: "Cortex response" })).toHaveTextContent(
      /evidence-backed answer/i,
    );
    expect(within(turn).getByRole("link", { name: "Graph explorer" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE.id}/graph`,
    );
    expect(within(turn).getByRole("link", { name: "Project sources" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE.id}/sources`,
    );
    expect(screen.getByLabelText(/ask cortex about this workspace/i)).toHaveValue(
      "",
    );
    expect(screen.getByLabelText(/ask cortex about this workspace/i)).toHaveFocus();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Why Neo4j?",
    );
  });

  it("starts a new conversation from the session header", async () => {
    const user = userEvent.setup();
    renderWorkspaceDetail();
    const input = screen.getByLabelText(/ask cortex about this workspace/i);

    await user.type(input, "Why Neo4j?");
    await user.click(screen.getByRole("button", { name: /send question/i }));
    await user.click(
      screen.getByRole("button", { name: "New conversation" }),
    );

    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Graph-Aware Assistant",
    );
    expect(input).toHaveFocus();
  });

  it("turns suggested follow-ups into editable questions", async () => {
    const user = userEvent.setup();
    renderWorkspaceDetail();
    const input = screen.getByLabelText(/ask cortex about this workspace/i);

    await user.type(input, "Why Neo4j?");
    await user.click(screen.getByRole("button", { name: /send question/i }));
    await user.click(
      screen.getByRole("button", { name: "Trace the related decisions" }),
    );

    expect(input).toHaveValue("Trace the related decisions");
    expect(input).toHaveFocus();
  });

  it("keeps earlier messages when a follow-up question is submitted", async () => {
    const user = userEvent.setup();
    renderWorkspaceDetail();
    const input = screen.getByLabelText(/ask cortex about this workspace/i);

    await user.type(input, "Why Neo4j?");
    await user.click(screen.getByRole("button", { name: /send question/i }));
    await user.type(input, "What data is stored there?");
    await user.click(screen.getByRole("button", { name: /send question/i }));

    const turns = screen.getAllByRole("article");
    expect(turns).toHaveLength(2);
    expect(turns[0]).toHaveTextContent("Why Neo4j?");
    expect(turns[1]).toHaveTextContent("What data is stored there?");
  });

  it("submits with Enter while keeping Shift+Enter available for a new line", async () => {
    const user = userEvent.setup();
    renderWorkspaceDetail();
    const input = screen.getByLabelText(/ask cortex about this workspace/i);

    await user.type(input, "First line{Shift>}{Enter}{/Shift}Second line");
    expect(input).toHaveValue("First line\nSecond line");

    await user.type(input, "{Enter}");

    expect(screen.getByRole("article", { name: "Conversation turn 1" })).toHaveTextContent(
      "First line Second line",
    );
  });
});
