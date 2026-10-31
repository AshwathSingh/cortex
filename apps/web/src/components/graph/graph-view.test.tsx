import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GraphView } from "@/components/graph/graph-view";
import type { GraphEdge, GraphNode, WorkspaceGraph } from "@/lib/api-types";

const { routerMock } = vi.hoisted(() => {
  const replace = vi.fn();
  return { routerMock: { replace, push: vi.fn(), refresh: vi.fn() } };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));
vi.mock("@/components/graph/graph-canvas", () => ({
  GraphCanvas: ({ onSelectionChange }: { onSelectionChange: (selection: unknown) => void }) => (
    <div>
      <button onClick={() => onSelectionChange({ kind: "node", key: "PullRequest:20" })}>Select node</button>
      <button onClick={() => onSelectionChange({ kind: "edge", edge: { source: "Author:1", target: "PullRequest:20", type: "AUTHORED" } })}>Select edge</button>
      <button onClick={() => onSelectionChange(null)}>Blank canvas</button>
      <button onClick={() => onSelectionChange({ kind: "node", key: MESSAGE_KEY })}>Select message</button>
    </div>
  ),
}));

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";
/** A chat node id carries its channel and is not an integer (US-08). */
const MESSAGE_KEY = "Message:slack/C0ABC/1730000000.000100";
const node: GraphNode = {
  key: "PullRequest:20", id: 20, type: "PullRequest", title: "#3 Add graph details",
  url: "https://github.com/acme/repo/pull/3", state: "open", repo: "acme/repo", number: 3,
};
const edge: GraphEdge = { source: "Author:1", target: node.key, type: "AUTHORED" };
const graph: WorkspaceGraph = { workspace_id: WORKSPACE_ID, nodes: [node], edges: [edge], truncated: false };
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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("GraphView inspector flow", () => {
  it("loads selected node details and closes when blank canvas is selected", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/graph")) return Promise.resolve(jsonResponse(graph));
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
      if (!String(input).endsWith("/graph")) return Promise.resolve(jsonResponse(nodeDetails));
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

    // What is on screen is still the last thing the server successfully sent;
    // replacing it with an error would lose work the user can still read.
    expect(screen.getByRole("button", { name: "Select node" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names every node type in the legend, chat included", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(graph))));
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    await screen.findByRole("button", { name: "Select node" });

    for (const label of ["Author", "Pull request", "Issue", "Channel", "Message"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("fetches a chat message's details by its slash-separated id", async () => {
    const messageKey = MESSAGE_KEY;
    const message: GraphNode = {
      key: messageKey, id: "slack/C0ABC/1730000000.000100", type: "Message",
      title: "We are going with Postgres", url: "https://slack.com/app_redirect?channel=C0ABC",
      state: null, repo: null, number: null,
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/graph")) {
        return Promise.resolve(
          jsonResponse({ ...graph, nodes: [message], edges: [] }),
        );
      }
      return Promise.resolve(
        jsonResponse({
          key: messageKey, id: message.id, type: "Message", title: message.title,
          content: "We are going with Postgres", attributes: {},
          origins: [{
            key: messageKey, type: "Message", title: message.title,
            url: message.url!, relationship: null, direction: null,
          }],
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<GraphView workspaceId={WORKSPACE_ID} />);

    fireEvent.click(await screen.findByRole("button", { name: "Select message" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).includes("/graph/nodes/Message/"),
        ),
      ).toBe(true),
    );
    // encodeURIComponent turns the id's slashes into %2F; the route's :path
    // converter is what puts them back.
    const detailCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/graph/nodes/Message/"),
    )!;
    expect(String(detailCall[0])).toContain("slack%2FC0ABC%2F1730000000.000100");
  });

  it("requests selected edge evidence and renders its connected sources", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/graph")) return Promise.resolve(jsonResponse(graph));
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
