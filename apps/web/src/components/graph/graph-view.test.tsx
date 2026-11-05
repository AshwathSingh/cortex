import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GraphView } from "@/components/graph/graph-view";
import type { GraphEdge, GraphNode, WorkspaceGraph } from "@/lib/api-types";

const { routerMock } = vi.hoisted(() => {
  const replace = vi.fn();
  return { routerMock: { replace, push: vi.fn(), refresh: vi.fn() } };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));
vi.mock("@/components/graph/graph-canvas", () => ({
  GraphCanvas: ({
    nodes,
    edges,
    highlightedNodeKeys,
    onSelectionChange,
  }: {
    nodes: GraphNode[];
    edges: GraphEdge[];
    highlightedNodeKeys?: string[];
    onSelectionChange: (selection: unknown) => void;
  }) => (
    <div>
      <output data-testid="visible-node-keys">{nodes.map((item) => item.key).join(",")}</output>
      <output data-testid="visible-edge-count">{edges.length}</output>
      <output data-testid="highlighted-node-keys">{highlightedNodeKeys?.join(",") ?? ""}</output>
      <button onClick={() => onSelectionChange({ kind: "node", key: "PullRequest:20" })}>Select node</button>
      <button onClick={() => onSelectionChange({ kind: "node", key: "Issue:30" })}>Select issue</button>
      <button onClick={() => onSelectionChange({ kind: "edge", edge: { source: "Author:1", target: "PullRequest:20", type: "AUTHORED" } })}>Select edge</button>
      <button onClick={() => onSelectionChange(null)}>Blank canvas</button>
    </div>
  ),
}));

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";
const node: GraphNode = {
  key: "PullRequest:20", id: 20, type: "PullRequest", title: "#3 Add graph details",
  url: "https://github.com/acme/repo/pull/3", state: "open", repo: "acme/repo", number: 3,
};
const edge: GraphEdge = { source: "Author:1", target: node.key, type: "AUTHORED" };
const graph: WorkspaceGraph = {
  workspace_id: WORKSPACE_ID,
  nodes: [
    { key: "Author:1", id: 1, type: "Author", title: "alice", url: null, state: null, repo: null, number: null },
    node,
  ],
  edges: [edge],
  truncated: false,
};
const filterGraph: WorkspaceGraph = {
  workspace_id: WORKSPACE_ID,
  nodes: [
    { key: "Author:1", id: 1, type: "Author", title: "alice", url: null, state: null, repo: null, number: null },
    node,
    { key: "Issue:30", id: 30, type: "Issue", title: "#4 Bug", url: null, state: "open", repo: "acme/repo", number: 4 },
  ],
  edges: [
    { source: "Author:1", target: node.key, type: "AUTHORED" },
    { source: node.key, target: "Issue:30", type: "RELATED_TO" },
  ],
  truncated: false,
};
const mutationGraph: WorkspaceGraph = {
  ...filterGraph,
  edges: [edge],
};
const nodeDetails = {
  key: node.key, id: node.id, type: node.type, title: node.title, content: "Change details",
  attributes: { state: "open" },
  origins: [{ key: node.key, type: node.type, title: node.title, url: node.url!, relationship: null, direction: null }],
};
const edgeDetails = {
  key: "Author:1|AUTHORED|PullRequest:20", type: "AUTHORED", title: "Authored",
  content: "Alice authored this pull request.",
  source: { ...nodeDetails, key: "Author:1", id: 1, type: "Author", title: "alice" },
  target: nodeDetails, attributes: {}, origins: nodeDetails.origins,
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value() {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value() {
      this.removeAttribute("open");
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("GraphView inspector flow", () => {
  it("loads selected node details and closes when blank canvas is selected", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (new URL(url, "http://localhost").pathname.endsWith("/graph")) return Promise.resolve(jsonResponse(graph));
      return Promise.resolve(jsonResponse(nodeDetails));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    fireEvent.click(await screen.findByRole("button", { name: "Select node" }));
    expect(await screen.findByText("Change details")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/workspaces/${WORKSPACE_ID}/graph/nodes/PullRequest/20`,
      expect.objectContaining({ credentials: "same-origin" }),
    ));

    fireEvent.click(screen.getByRole("button", { name: "Blank canvas" }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: /node details/i })).not.toBeInTheDocument());
  });

  it("keeps the graph on screen when a background refresh fails", async () => {
    let graphReads = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (!new URL(String(input), "http://localhost").pathname.endsWith("/graph")) return Promise.resolve(jsonResponse(nodeDetails));
      graphReads += 1;
      return Promise.resolve(
        graphReads === 1
          ? jsonResponse(graph)
          : new Response(JSON.stringify({ detail: "Graph database unavailable" }), {
              status: 503,
              headers: { "Content-Type": "application/json" },
            }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = render(<GraphView workspaceId={WORKSPACE_ID} reloadToken={0} />);
    await screen.findByRole("button", { name: "Select node" });

    // A re-sync bumps the token, so the graph is refetched -- and this time the
    // server is down.
    rerender(<GraphView workspaceId={WORKSPACE_ID} reloadToken={1} />);
    await waitFor(() => expect(graphReads).toBe(2));

    // Keep the last successful graph visible and explain why its refresh failed.
    expect(screen.getByRole("button", { name: "Select node" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Graph database unavailable");
  });

  it("requests selected edge evidence and renders its connected sources", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (new URL(url, "http://localhost").pathname.endsWith("/graph")) return Promise.resolve(jsonResponse(graph));
      return Promise.resolve(jsonResponse(edgeDetails));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    fireEvent.click(await screen.findByRole("button", { name: "Select edge" }));
    expect(await screen.findByText("Alice authored this pull request.")).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    await waitFor(() => expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain(
      "/graph/edges?source_key=Author%3A1&target_key=PullRequest%3A20&edge_type=AUTHORED",
    ));
  });
});

describe("GraphView relationship mutations", () => {
  it("hides create and delete controls from read-only users", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("/graph/edges?")) return Promise.resolve(jsonResponse(edgeDetails));
      return Promise.resolve(jsonResponse(mutationGraph));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<GraphView workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByRole("button", { name: "Select edge" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create relationship" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select edge" }));
    expect(await screen.findByText(edgeDetails.content)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove relationship" })).not.toBeInTheDocument();
  });

  it("creates a relationship for a workspace writer", async () => {
    const user = userEvent.setup();
    const manualEdge = {
      source: "PullRequest:20",
      target: "Issue:30",
      type: "MANUAL_RELATIONSHIP",
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") return Promise.resolve(jsonResponse(manualEdge));
      return Promise.resolve(jsonResponse(mutationGraph));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<GraphView workspaceId={WORKSPACE_ID} canEdit />);

    await user.click(await screen.findByRole("button", { name: "Create relationship" }));
    expect(screen.getByText("Choose the first node")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Select node" }));
    expect(screen.getByText("Now choose the second node")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Select issue" }));

    const dialog = screen.getByRole("dialog", { name: "Create relationship" });
    expect(dialog).toBeVisible();
    expect(screen.getByText("#3 Add graph details")).toBeInTheDocument();
    expect(screen.getByText("#4 Bug")).toBeInTheDocument();
    expect(screen.getByLabelText("Why are these nodes connected?")).toHaveFocus();

    await user.type(
      screen.getByLabelText("Why are these nodes connected?"),
      "They address the same change.",
    );
    await user.click(screen.getAllByRole("button", { name: "Create relationship" }).at(-1)!);

    expect(await screen.findByText("Relationship added.")).toBeInTheDocument();
    expect(screen.getByTestId("visible-edge-count")).toHaveTextContent("2");
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/workspaces/${WORKSPACE_ID}/graph/edges`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          source_key: "PullRequest:20",
          target_key: "Issue:30",
          relationship_type: "RELATED_TO",
          rationale: "They address the same change.",
        }),
      }),
    );
  });

  it("does not create a relationship when the rationale prompt is cancelled", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse(mutationGraph)));
    vi.stubGlobal("fetch", fetchMock);

    render(<GraphView workspaceId={WORKSPACE_ID} canEdit />);

    await user.click(await screen.findByRole("button", { name: "Create relationship" }));
    await user.click(screen.getByRole("button", { name: "Select node" }));
    await user.click(screen.getByRole("button", { name: "Select issue" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByText("Relationship creation cancelled.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("deletes a selected relationship for a workspace writer", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "DELETE") return Promise.resolve(jsonResponse({ deleted: true }));
      if (String(input).includes("/graph/edges?")) return Promise.resolve(jsonResponse(edgeDetails));
      return Promise.resolve(jsonResponse(mutationGraph));
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<GraphView workspaceId={WORKSPACE_ID} canEdit />);

    fireEvent.click(await screen.findByRole("button", { name: "Select edge" }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove relationship" }));

    expect(await screen.findByText("Relationship removed.")).toBeInTheDocument();
    expect(screen.getByTestId("visible-edge-count")).toHaveTextContent("0");
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/workspaces/${WORKSPACE_ID}/graph/edges`,
      expect.objectContaining({
        method: "DELETE",
        body: JSON.stringify({
          source_key: "Author:1",
          target_key: "PullRequest:20",
          edge_type: "AUTHORED",
        }),
      }),
    );
  });
});

describe("GraphView artifact filters", () => {
  it("reactively filters nodes and keeps edges only when both endpoints remain", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      void input;
      return Promise.resolve(jsonResponse(filterGraph));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByTestId("visible-node-keys")).toHaveTextContent(
      "Author:1,PullRequest:20,Issue:30",
    );
    expect(screen.getByTestId("visible-edge-count")).toHaveTextContent("2");

    fireEvent.click(screen.getByRole("button", { name: "Issue" }));
    expect(screen.getByTestId("visible-node-keys")).toHaveTextContent(
      "Author:1,PullRequest:20",
    );
    expect(screen.getByTestId("visible-edge-count")).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: "Issue" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await waitFor(() => expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("types=Author&types=PullRequest"));

    fireEvent.click(screen.getByRole("button", { name: "Author" }));
    expect(screen.getByTestId("visible-node-keys")).toHaveTextContent("PullRequest:20");
    expect(screen.getByTestId("visible-edge-count")).toHaveTextContent("0");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("shows a clear empty graph state when no artifact types are selected", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(filterGraph))));
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    await screen.findByTestId("visible-node-keys");
    for (const type of ["Author", "Pull request", "Issue"]) {
      fireEvent.click(screen.getByRole("button", { name: type }));
    }

    expect(screen.getByRole("heading", { name: "No artifacts match these filters" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show all artifact types" })).toBeInTheDocument();
    expect(screen.queryByTestId("visible-node-keys")).not.toBeInTheDocument();
  });

  it("searches by keyword and highlights the matching graph nodes", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      return Promise.resolve(jsonResponse(url.includes("?q=graph") ? filterGraph : graph));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    await screen.findByTestId("visible-node-keys");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search artifacts" }), {
      target: { value: "graph" },
    });
    fireEvent.submit(screen.getByRole("search"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/workspaces/${WORKSPACE_ID}/graph?q=graph&types=Author&types=PullRequest&types=Issue`,
      expect.objectContaining({ credentials: "same-origin" }),
    ));
    await waitFor(() => expect(screen.getByTestId("highlighted-node-keys")).toHaveTextContent(
      "Author:1,PullRequest:20,Issue:30",
    ));
  });

  it("does not highlight the previous graph when a search request fails", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("?q=missing")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "Graph database unavailable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }));
      }
      return Promise.resolve(jsonResponse(graph));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    await screen.findByTestId("visible-node-keys");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search artifacts" }), {
      target: { value: "missing" },
    });
    fireEvent.submit(screen.getByRole("search"));

    expect(await screen.findByText("Graph database unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("visible-node-keys")).toHaveTextContent("Author:1,PullRequest:20");
    expect(screen.getByTestId("highlighted-node-keys")).toBeEmptyDOMElement();
  });

  it("shows an empty graph state when a keyword has no matches", async () => {
    const emptyGraph = { ...graph, nodes: [], edges: [] };
    const fetchMock = vi.fn((input: RequestInfo | URL) => Promise.resolve(
      jsonResponse(String(input).includes("?q=absent") ? emptyGraph : graph),
    ));
    vi.stubGlobal("fetch", fetchMock);
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    await screen.findByTestId("visible-node-keys");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search artifacts" }), {
      target: { value: "absent" },
    });
    fireEvent.submit(screen.getByRole("search"));

    expect(await screen.findByRole("heading", { name: "No artifacts match “absent”" })).toBeInTheDocument();
    expect(screen.queryByTestId("visible-node-keys")).not.toBeInTheDocument();
  });

  it("uses one active-search control with inline clear and keyboard reset", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) =>
      Promise.resolve(jsonResponse(String(input).includes("?q=graph") ? filterGraph : graph)),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    const searchbox = await screen.findByRole("searchbox", {
      name: "Search artifacts",
    });
    expect(searchbox).toHaveAttribute("type", "text");
    expect(searchbox).toHaveAttribute("inputmode", "search");
    expect(screen.queryByRole("button", { name: "Search" })).not.toBeInTheDocument();

    fireEvent.change(searchbox, { target: { value: "graph" } });
    expect(screen.getByRole("button", { name: "Clear search" })).toBeInTheDocument();
    fireEvent.submit(screen.getByRole("search"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/workspaces/${WORKSPACE_ID}/graph?q=graph&types=Author&types=PullRequest&types=Issue`,
      expect.anything(),
    ));

    fireEvent.keyDown(searchbox, { key: "Escape" });
    expect(searchbox).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Clear search" })).not.toBeInTheDocument();
  });
});
