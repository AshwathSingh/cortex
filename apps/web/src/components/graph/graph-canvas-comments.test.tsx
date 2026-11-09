import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GraphCanvas } from "@/components/graph/graph-canvas";
import type { CommentActivity, GraphNode } from "@/lib/api-types";

/**
 * T-27.4: marking the nodes and edges that carry comments, so a reader can see
 * where the conversations are without opening anything (AC2).
 *
 * The badge is read off the canvas calls: a filled dot for unseen, a ring for
 * already-read. Both are `arc` calls at radii nothing else in the scene uses,
 * which is what makes them findable here.
 */

const UNSEEN_RADIUS = 5.4;
const SEEN_RADIUS = 4.4;

type Ctx2D = Record<string, ReturnType<typeof vi.fn>>;

function stubCanvas(): Ctx2D {
  const ctx: Ctx2D = {
    clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
    stroke: vi.fn(), arc: vi.fn(), rect: vi.fn(), closePath: vi.fn(),
    fill: vi.fn(), fillText: vi.fn(), setTransform: vi.fn(), save: vi.fn(),
    restore: vi.fn(), translate: vi.fn(), scale: vi.fn(),
    measureText: vi.fn((text: string) => ({ width: text.length * 6 })),
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
  node("Author:2", "Author", "bob"),
  node("Issue:42", "Issue", "#2 Bug"),
];

const EDGES = [{ source: "Author:1", target: "Issue:42", type: "AUTHORED" }];
const EDGE_KEY = "Author:1|AUTHORED|Issue:42";

function activity(over: Partial<CommentActivity> = {}): CommentActivity {
  return {
    target_kind: "node",
    target_key: "Issue:42",
    total: 1,
    unseen: 1,
    ...over,
  };
}

/** Distinct positions where a badge of this radius was drawn. */
function badgesAt(ctx: Ctx2D, radius: number) {
  const seen = new Set<string>();
  for (const [x, y, r] of ctx.arc.mock.calls as number[][]) {
    if (Math.abs(Number(r) - radius) < 1e-9) {
      seen.add(`${Math.round(Number(x))},${Math.round(Number(y))}`);
    }
  }
  return seen;
}

function nodeShapes(ctx: Ctx2D) {
  // Every `arc` that is not a badge: the circles the Author nodes are drawn as.
  return (ctx.arc.mock.calls as number[][])
    .filter(([, , r]) => Math.abs(Number(r) - UNSEEN_RADIUS) > 1e-9
      && Math.abs(Number(r) - SEEN_RADIUS) > 1e-9)
    .map(([x, y]) => `${Math.round(Number(x))},${Math.round(Number(y))}`);
}

beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", vi.fn().mockReturnValue(1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mount(commentActivity?: CommentActivity[]) {
  const ctx = stubCanvas();
  const utils = render(
    <GraphCanvas nodes={NODES} edges={EDGES} commentActivity={commentActivity} />,
  );
  return { ctx, utils };
}

describe("comment badges", () => {
  it("draws nothing when nothing is commented on", () => {
    const { ctx } = mount([]);

    expect(badgesAt(ctx, UNSEEN_RADIUS).size).toBe(0);
    expect(badgesAt(ctx, SEEN_RADIUS).size).toBe(0);
  });

  it("draws nothing when the prop is absent entirely", () => {
    const { ctx } = mount();

    expect(badgesAt(ctx, UNSEEN_RADIUS).size).toBe(0);
  });

  it("marks a node with unseen comments", () => {
    const { ctx } = mount([activity()]);

    expect(badgesAt(ctx, UNSEEN_RADIUS).size).toBe(1);
    expect(badgesAt(ctx, SEEN_RADIUS).size).toBe(0);
  });

  it("marks a node whose comments have all been read differently", () => {
    /** Filled versus hollow, not one colour versus another: the distinction has
     *  to survive a colour-blind reader and a greyscale screenshot. */
    const { ctx } = mount([activity({ unseen: 0 })]);

    expect(badgesAt(ctx, SEEN_RADIUS).size).toBe(1);
    expect(badgesAt(ctx, UNSEEN_RADIUS).size).toBe(0);
  });

  it("marks an edge at the midpoint of its endpoints", () => {
    /**
     * A two-node graph, so both endpoint centres are recoverable exactly: an
     * Author is a circle (`arc`) and a pull request is a square whose `rect`
     * call gives its centre back.
     */
    const pair: GraphNode[] = [
      node("Author:1", "Author", "alice"),
      node("PullRequest:100", "PullRequest", "#1 Add thing"),
    ];
    const edge = { source: "Author:1", target: "PullRequest:100", type: "AUTHORED" };
    const ctx = stubCanvas();
    render(
      <GraphCanvas
        nodes={pair}
        edges={[edge]}
        commentActivity={[
          activity({
            target_kind: "edge",
            target_key: "Author:1|AUTHORED|PullRequest:100",
          }),
        ]}
      />,
    );

    const [authorCentre] = [...new Set(nodeShapes(ctx))];
    const [ax, ay] = authorCentre.split(",").map(Number);
    const [rx, ry, rw, rh] = (ctx.rect.mock.calls[0] as number[]).map(Number);
    const squareCentre = [rx + rw / 2, ry + rh / 2];

    const [badge] = [...badgesAt(ctx, UNSEEN_RADIUS)];
    expect(badge).toBe(
      `${Math.round((ax + squareCentre[0]) / 2)},${Math.round((ay + squareCentre[1]) / 2)}`,
    );
  });

  it("marks several targets at once", () => {
    const { ctx } = mount([
      activity({ target_key: "Issue:42" }),
      activity({ target_key: "Author:1" }),
      activity({ target_kind: "edge", target_key: EDGE_KEY }),
    ]);

    expect(badgesAt(ctx, UNSEEN_RADIUS).size).toBe(3);
  });

  it("does not confuse a node with an edge of the same key", () => {
    const { ctx } = mount([
      activity({ target_kind: "edge", target_key: "Issue:42" }),
    ]);

    // There is no edge with that key, so nothing is marked.
    expect(badgesAt(ctx, UNSEEN_RADIUS).size).toBe(0);
  });

  it("ignores a target that is not on the canvas", () => {
    const { ctx } = mount([activity({ target_key: "Issue:9999" })]);

    expect(badgesAt(ctx, UNSEEN_RADIUS).size).toBe(0);
  });

  it("repaints a changed badge without moving a single node", () => {
    /** The badge changes whenever somebody comments or the reader opens a
     *  thread. Rebuilding the layout for that would re-seed every node, which
     *  is exactly the bug P-14.1 fixed. */
    const ctx = stubCanvas();
    const { rerender } = render(
      <GraphCanvas nodes={NODES} edges={EDGES} commentActivity={[activity()]} />,
    );
    const positionsBefore = nodeShapes(ctx);
    expect(badgesAt(ctx, UNSEEN_RADIUS).size).toBe(1);
    ctx.arc.mockClear();

    rerender(
      <GraphCanvas
        nodes={NODES}
        edges={EDGES}
        commentActivity={[activity({ unseen: 0 })]}
      />,
    );

    expect(nodeShapes(ctx)).toEqual(positionsBefore);
    expect(badgesAt(ctx, SEEN_RADIUS).size).toBe(1);
    expect(badgesAt(ctx, UNSEEN_RADIUS).size).toBe(0);
  });
});
