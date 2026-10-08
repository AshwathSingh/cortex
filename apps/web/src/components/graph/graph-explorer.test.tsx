import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  GraphCanvas,
  nodeColour,
  nodeShape,
} from "@/components/graph/graph-canvas";
import { GraphExplorer } from "@/components/graph/graph-explorer";
import type { GraphEdge, GraphNode, WorkspaceGraph } from "@/lib/api-types";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";
/** Each node renders as halo fill + ring stroke + centre mark. */
const PATHS_PER_NODE = 3;

// The router object must be STABLE across renders. `useRouter` is in the
// effect's dependency list, so returning a fresh object each call re-runs the
// effect, which sets state, which renders again — an infinite loop. Next's real
// useRouter returns a stable reference; the mock has to as well.
const { replace, routerMock } = vi.hoisted(() => {
  const replaceFn = vi.fn();
  return {
    replace: replaceFn,
    routerMock: { replace: replaceFn, push: vi.fn(), refresh: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

/**
 * jsdom implements no canvas 2d context, so getContext returns null and nothing
 * would be drawn. Stub it with spies and assert the draw calls instead — that is
 * the only way to verify canvas rendering without a real browser.
 */
type Ctx2D = Record<string, ReturnType<typeof vi.fn>>;

function stubCanvas(): Ctx2D {
  const ctx: Ctx2D = {
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    rect: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    fillText: vi.fn(),
    setTransform: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    scale: vi.fn(),
    // Real 2d contexts always have this; the label collision pass needs it.
    measureText: vi.fn((t: string) => ({ width: t.length * 6 })),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  );
  return ctx;
}

function node(key: string, type: GraphNode["type"], title: string): GraphNode {
  return { key, id: 1, type, title, url: null, state: null, repo: null, number: null };
}

const NODES: GraphNode[] = [
  node("Author:1", "Author", "alice"),
  node("PullRequest:100", "PullRequest", "#1 Add thing"),
  node("Issue:200", "Issue", "#2 Bug"),
];
const EDGES: GraphEdge[] = [
  { source: "Author:1", target: "PullRequest:100", type: "AUTHORED" },
  { source: "Author:1", target: "Issue:200", type: "AUTHORED" },
];

function graph(over: Partial<WorkspaceGraph> = {}): WorkspaceGraph {
  return {
    workspace_id: WORKSPACE_ID,
    nodes: NODES,
    edges: EDGES,
    truncated: false,
    ...over,
  };
}

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => {
  replace.mockClear();
  // Capture the frame callback without running it. Invoking it synchronously
  // would recurse through the whole cooling schedule in one stack (~140 frames)
  // and abort the worker; a real browser schedules each frame separately.
  // The component paints once before requesting a frame, so the assertions below
  // describe that first paint.
  vi.stubGlobal("requestAnimationFrame", vi.fn().mockReturnValue(1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("GraphCanvas", () => {
  it("draws a ring, halo and centre mark for every node", () => {
    const ctx = stubCanvas();
    render(<GraphCanvas nodes={NODES} edges={[]} />);
    expect(ctx.beginPath).toHaveBeenCalledTimes(NODES.length * PATHS_PER_NODE);
    expect(ctx.fill).toHaveBeenCalled();
    expect(ctx.stroke).toHaveBeenCalled();
  });

  it("distinguishes node types by shape, not only by colour", () => {
    expect(new Set(["Author", "PullRequest", "Issue"].map(nodeShape)).size).toBe(3);

    const ctx = stubCanvas();
    render(<GraphCanvas nodes={NODES} edges={[]} />);
    expect(ctx.arc).toHaveBeenCalled();
    expect(ctx.rect).toHaveBeenCalled();
    expect(ctx.closePath).toHaveBeenCalled();
  });

  it("uses a resolvable font and pixel-snapped labels (crispness)", () => {
    const ctx = stubCanvas();
    render(<GraphCanvas nodes={NODES} edges={[]} />);

    // Canvas `font` is CSS-parsed but does NOT resolve custom properties. A
    // `var(--font-...)` here is invalid, so the assignment is dropped and every
    // label silently falls back to the default 10px sans-serif — which is what
    // made the text look blurry and undersized.
    expect(String((ctx as unknown as { font: string }).font)).not.toContain("var(");

    // Fractional coordinates resample text across two pixel columns.
    for (const call of ctx.fillText.mock.calls) {
      expect(Number.isInteger(call[1])).toBe(true);
      expect(Number.isInteger(call[2])).toBe(true);
    }
  });

  it("draws one line per edge", () => {
    const ctx = stubCanvas();
    const nodes = NODES.slice(0, 2); // circle + square; neither uses lineTo
    const edges = EDGES.slice(0, 1);
    render(<GraphCanvas nodes={nodes} edges={edges} />);
    expect(ctx.moveTo).toHaveBeenCalledTimes(edges.length);
    expect(ctx.lineTo).toHaveBeenCalledTimes(edges.length);
    // stroke() also draws each node's rim, so it runs more often than once per edge.
    expect(ctx.stroke).toHaveBeenCalled();
  });

  it("labels nodes on a small graph", () => {
    const ctx = stubCanvas();
    render(<GraphCanvas nodes={NODES} edges={[]} />);
    const drawn = ctx.fillText.mock.calls.map((call) => call[0]);
    expect(drawn).toContain("alice");
  });

  it("suppresses labels that would collide on a crowded graph", () => {
    // Every node is still drawn, but a label is skipped rather than stacked on
    // top of one already placed — so labels drawn < nodes, and none overlap.
    const ctx = stubCanvas();
    const many = Array.from({ length: 120 }, (_, i) =>
      node(`PullRequest:${i}`, "PullRequest", `#${i} a reasonably long title`),
    );
    render(<GraphCanvas nodes={many} edges={[]} />);
    expect(ctx.beginPath).toHaveBeenCalledTimes(120 * PATHS_PER_NODE);
    expect(ctx.fillText.mock.calls.length).toBeGreaterThan(0);
    expect(ctx.fillText.mock.calls.length).toBeLessThan(120);
  });

  it("does not draw an edge whose endpoint is missing", () => {
    const ctx = stubCanvas();
    render(
      <GraphCanvas
        nodes={[node("Author:1", "Author", "alice")]}
        edges={[{ source: "Author:1", target: "PullRequest:999", type: "AUTHORED" }]}
      />,
    );
    expect(ctx.moveTo).not.toHaveBeenCalled();
  });

  it("survives a browser with no 2d context", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    expect(() => render(<GraphCanvas nodes={NODES} edges={EDGES} />)).not.toThrow();
  });

  it("describes the graph for screen readers", () => {
    stubCanvas();
    render(<GraphCanvas nodes={NODES} edges={EDGES} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(
      "Knowledge graph: 3 nodes, 2 connections",
    );
  });

  it("remeasures when its container resizes", () => {
    stubCanvas();
    let resize: (() => void) | undefined;
    const observe = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resize = callback;
        }
        observe = observe;
        disconnect = vi.fn();
      },
    );
    render(<GraphCanvas nodes={NODES} edges={EDGES} />);
    const canvas = screen.getByRole("img") as HTMLCanvasElement;
    const parent = canvas.parentElement as HTMLElement;
    Object.defineProperty(parent, "clientWidth", { configurable: true, value: 720 });

    resize?.();

    expect(observe).toHaveBeenCalledWith(parent);
    expect(canvas.style.width).toBe("720px");
  });

  it("gives each existing node type its own colour", () => {
    const colours = ["Author", "PullRequest", "Issue"].map(nodeColour);
    expect(new Set(colours).size).toBe(3);
  });

  it("offers accessible zoom controls and restores the default view", () => {
    const ctx = stubCanvas();
    render(<GraphCanvas nodes={NODES} edges={EDGES} />);

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("120%")).toBeInTheDocument();
    expect(ctx.scale).toHaveBeenLastCalledWith(1.2, 1.2);

    fireEvent.click(screen.getByRole("button", { name: "Reset view" }));
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(ctx.translate).toHaveBeenLastCalledWith(0, 0);
    expect(ctx.scale).toHaveBeenLastCalledWith(1, 1);
  });

  it("pans the graph without treating the drag as a selection", () => {
    const ctx = stubCanvas();
    const onSelectionChange = vi.fn();
    render(
      <GraphCanvas
        nodes={NODES}
        edges={EDGES}
        onSelectionChange={onSelectionChange}
      />,
    );
    const canvas = screen.getByRole("img");

    fireEvent.pointerDown(canvas, {
      button: 0,
      pointerId: 1,
      clientX: 40,
      clientY: 40,
    });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 80, clientY: 65 });
    fireEvent.pointerUp(canvas, { pointerId: 1, clientX: 80, clientY: 65 });
    fireEvent.click(canvas, { clientX: 80, clientY: 65 });

    expect(ctx.translate).toHaveBeenLastCalledWith(40, 25);
    expect(onSelectionChange).not.toHaveBeenCalled();
  });
});

describe("GraphExplorer", () => {
  it("fetches the graph for the active workspace only", async () => {
    stubCanvas();
    const fetchFn = mockFetch(200, graph());
    render(<GraphExplorer workspaceId={WORKSPACE_ID} />);

    await waitFor(() => expect(fetchFn).toHaveBeenCalled());
    expect(fetchFn.mock.calls[0][0]).toBe(
      `/api/workspaces/${WORKSPACE_ID}/graph`,
    );
  });

  it("renders the canvas with node and connection counts", async () => {
    stubCanvas();
    mockFetch(200, graph());
    render(<GraphExplorer workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByRole("img")).toBeInTheDocument();
    expect(screen.getByText("3 nodes · 2 connections")).toBeInTheDocument();
  });

  it("legends only the node types that exist today", async () => {
    stubCanvas();
    mockFetch(200, graph());
    render(<GraphExplorer workspaceId={WORKSPACE_ID} />);

    const legend = await screen.findByRole("list", { name: /node types/i });
    expect(legend).toHaveTextContent("Author");
    expect(legend).toHaveTextContent("Pull request");
    expect(legend).toHaveTextContent("Issue");
  });

  it("offers ingestion when the workspace is empty", async () => {
    mockFetch(200, graph({ nodes: [], edges: [] }));
    render(<GraphExplorer workspaceId={WORKSPACE_ID} />);

    expect(
      await screen.findByText(/your graph starts with a source/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /add a github repository/i }),
    ).toHaveAttribute("href", `/workspaces/${WORKSPACE_ID}/ingest`);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("warns when the server truncated the graph", async () => {
    stubCanvas();
    mockFetch(200, graph({ truncated: true }));
    render(<GraphExplorer workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByRole("status")).toHaveTextContent(
      /display limit reached/i,
    );
  });

  it("shows the server message when access is refused", async () => {
    mockFetch(403, { detail: "You do not have access to this workspace" });
    render(<GraphExplorer workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /do not have access/i,
    );
  });

  it("redirects to login on 401", async () => {
    mockFetch(401, { detail: "Not authenticated" });
    render(<GraphExplorer workspaceId={WORKSPACE_ID} />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("reports an unreachable server", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    render(<GraphExplorer workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /unable to load the graph/i,
    );
  });

  it("uses the workspace sidebar for navigation instead of a duplicate back link", async () => {
    stubCanvas();
    mockFetch(200, graph());
    render(<GraphExplorer workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByRole("heading", { name: "Graph" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /back to workspace/i })).not.toBeInTheDocument();
  });
});
