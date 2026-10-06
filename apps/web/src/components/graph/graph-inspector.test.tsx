import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GraphInspector } from "@/components/graph/graph-inspector";
import type { GraphEdgeDetails, GraphNodeDetails } from "@/lib/api-types";

const nodeDetails: GraphNodeDetails = {
  key: "PullRequest:20",
  id: 20,
  type: "PullRequest",
  title: "#3 Add graph details",
  content: "A detailed description of the change.",
  attributes: { state: "open", repo: "acme/repo" },
  origins: [{
    key: "PullRequest:20",
    type: "PullRequest",
    title: "#3 Add graph details",
    url: "https://github.com/acme/repo/pull/3",
    relationship: null,
    direction: null,
  }],
};

const edgeDetails: GraphEdgeDetails = {
  key: "Author:1|AUTHORED|PullRequest:20",
  type: "AUTHORED",
  title: "Authored",
  content: "Alice authored this pull request.",
  source: { ...nodeDetails, key: "Author:1", id: 1, type: "Author", title: "alice" },
  target: nodeDetails,
  attributes: {},
  origins: nodeDetails.origins,
};

describe("GraphInspector", () => {
  it("shows node content, attributes, and source links opening in a new tab", () => {
    render(
      <GraphInspector
        selection={{ kind: "node", key: nodeDetails.key }}
        state={{ kind: "node", details: nodeDetails }}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: nodeDetails.title })).toBeInTheDocument();
    expect(screen.getByText(nodeDetails.content!)).toBeInTheDocument();
    expect(screen.getByText("open")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: nodeDetails.title })).toHaveAttribute(
      "href", "https://github.com/acme/repo/pull/3",
    );
    expect(screen.getByRole("link", { name: nodeDetails.title })).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: nodeDetails.title })).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows edge evidence and both endpoints", () => {
    render(
      <GraphInspector
        selection={{ kind: "edge", edge: { source: "Author:1", target: "PullRequest:20", type: "AUTHORED" } }}
        state={{ kind: "edge", details: edgeDetails }}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText(edgeDetails.content)).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getAllByText("#3 Add graph details")).toHaveLength(2);
  });

  it("reports loading and error states and closes on request", () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <GraphInspector
        selection={{ kind: "node", key: nodeDetails.key }}
        state={{ kind: "loading" }}
        onClose={onClose}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/loading graph details/i);
    fireEvent.click(screen.getByRole("button", { name: /close details/i }));
    expect(onClose).toHaveBeenCalledOnce();

    rerender(
      <GraphInspector
        selection={{ kind: "node", key: nodeDetails.key }}
        state={{ kind: "error", message: "Graph unavailable" }}
        onClose={onClose}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Graph unavailable");
  });
});
