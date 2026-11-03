import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantConversationProvider } from "@/components/workspaces/assistant-conversation-context";
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

const SECOND_WORKSPACE = {
  ...WORKSPACE,
  id: "workspace-2",
  name: "Platform Engineering",
} satisfies WorkspaceSummary;

const USER = {
  id: "user-1",
  email: "ash@example.com",
  display_name: "Ash Ketchum",
} satisfies AuthenticatedUser;

const ASSISTANT_RESPONSE = {
  answer:
    "This placeholder demonstrates how Cortex will present an evidence-backed answer.",
  citations: [
    {
      id: "workspace-graph",
      kind: "graph",
      label: "Graph explorer",
      description: "Inspect entities and relationships",
    },
    {
      id: "workspace-sources",
      kind: "sources",
      label: "Project sources",
      description: "Review the indexed source material",
    },
  ],
};

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

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
      <AssistantConversationProvider workspaceId={WORKSPACE.id}>
        <WorkspaceDetail workspaceId={WORKSPACE.id} />
      </AssistantConversationProvider>
    </WorkspaceProvider>,
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(() => jsonResponse(200, ASSISTANT_RESPONSE)),
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("WorkspaceDetail", () => {
  it("renders the shared workspace in the Cortex composer", () => {
    renderWorkspaceDetail();

    expect(
      screen.getByRole("heading", { level: 1, name: new RegExp(WORKSPACE.name) }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Graph-Aware Assistant")).not.toBeInTheDocument();
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
        level: 1,
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
          level: 1,
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
    expect(
      await within(turn).findByText(/evidence-backed answer/i),
    ).toBeInTheDocument();
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
    await screen.findByText(/evidence-backed answer/i);
    await user.click(
      screen.getByRole("button", { name: "New conversation" }),
    );

    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: new RegExp(WORKSPACE.name) }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "New conversation" }),
    ).not.toBeInTheDocument();
    expect(input).toHaveFocus();
  });

  it("starts with a blank conversation when the workspace changes", async () => {
    const user = userEvent.setup();
    const page = renderWorkspaceDetail();
    const input = screen.getByLabelText(/ask cortex about this workspace/i);

    await user.type(input, "Why Neo4j?");
    await user.click(screen.getByRole("button", { name: /send question/i }));

    page.rerender(
      <WorkspaceProvider
        value={{
          workspaceId: SECOND_WORKSPACE.id,
          workspace: SECOND_WORKSPACE,
          user: USER,
          isLoading: false,
          error: null,
        }}
      >
        <AssistantConversationProvider workspaceId={SECOND_WORKSPACE.id}>
          <WorkspaceDetail workspaceId={SECOND_WORKSPACE.id} />
        </AssistantConversationProvider>
      </WorkspaceProvider>,
    );

    await vi.waitFor(() =>
      expect(screen.queryByRole("article")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: new RegExp(SECOND_WORKSPACE.name),
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(`Workspace · ${SECOND_WORKSPACE.name}`)).toBeInTheDocument();
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
  });

  it("turns suggested follow-ups into editable questions", async () => {
    const user = userEvent.setup();
    renderWorkspaceDetail();
    const input = screen.getByLabelText(/ask cortex about this workspace/i);

    await user.type(input, "Why Neo4j?");
    await user.click(screen.getByRole("button", { name: /send question/i }));
    await screen.findByText(/evidence-backed answer/i);
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
    await screen.findByText(/evidence-backed answer/i);
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

  it("shows a pending state and prevents duplicate submissions", async () => {
    let resolveRequest: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveRequest = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWorkspaceDetail();
    const input = screen.getByLabelText(/ask cortex about this workspace/i);

    await user.type(input, "Why Neo4j?");
    await user.click(screen.getByRole("button", { name: /send question/i }));

    expect(screen.getByRole("status")).toHaveTextContent(/tracing the project graph/i);
    expect(input).toBeDisabled();
    expect(screen.getByRole("button", { name: "Waiting for Cortex" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledOnce();

    resolveRequest?.(
      new Response(JSON.stringify(ASSISTANT_RESPONSE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(await screen.findByText(/evidence-backed answer/i)).toBeInTheDocument();
    expect(input).toBeEnabled();
  });

  it("cancels an in-flight response when a new conversation starts", async () => {
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        requestSignal = init?.signal ?? undefined;
        return new Promise<Response>((_resolve, reject) => {
          requestSignal?.addEventListener("abort", () => {
            reject(new DOMException("The request was aborted.", "AbortError"));
          });
        });
      }),
    );
    const user = userEvent.setup();
    renderWorkspaceDetail();

    await user.type(
      screen.getByLabelText(/ask cortex about this workspace/i),
      "Why Neo4j?",
    );
    await user.click(screen.getByRole("button", { name: /send question/i }));
    await user.click(screen.getByRole("button", { name: "New conversation" }));

    expect(requestSignal?.aborted).toBe(true);
    await vi.waitFor(() =>
      expect(screen.queryByRole("article")).not.toBeInTheDocument(),
    );
    expect(screen.getByLabelText(/ask cortex about this workspace/i)).toBeEnabled();
  });

  it("shows backend errors and retries the same turn", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() =>
        jsonResponse(503, { detail: "The assistant is temporarily unavailable." }),
      )
      .mockImplementationOnce(() => jsonResponse(200, ASSISTANT_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderWorkspaceDetail();

    await user.type(
      screen.getByLabelText(/ask cortex about this workspace/i),
      "Why Neo4j?",
    );
    await user.click(screen.getByRole("button", { name: /send question/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /temporarily unavailable/i,
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/evidence-backed answer/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });
});
