import { describe, expect, it } from "vitest";

import {
  clampPan,
  graphPointFromCanvas,
  hitTestGraph,
  zoomViewport,
} from "@/components/graph/graph-canvas";
import type { GraphEdge } from "@/lib/api-types";

const edge: GraphEdge = {
  source: "Author:1",
  target: "PullRequest:20",
  type: "AUTHORED",
};

describe("graph canvas hit testing", () => {
  const nodes = [
    { key: "Author:1", x: 20, y: 20, radius: 12 },
    { key: "PullRequest:20", x: 120, y: 20, radius: 10 },
  ];
  const edges = [{ edge, x1: 20, y1: 20, x2: 120, y2: 20 }];

  it("selects a node when the pointer is on or near its graphic", () => {
    expect(hitTestGraph(20, 20, nodes, edges)).toEqual({ kind: "node", key: "Author:1" });
    expect(hitTestGraph(37, 20, nodes, edges)).toEqual({ kind: "node", key: "Author:1" });
  });

  it("selects the closest edge when the pointer is near its line", () => {
    expect(hitTestGraph(70, 26, nodes, edges)).toEqual({ kind: "edge", edge });
  });

  it("returns no selection on blank graph space", () => {
    expect(hitTestGraph(240, 180, nodes, edges)).toBeNull();
  });

  it("keeps the zoom anchor fixed and maps pointer coordinates back to graph space", () => {
    const viewport = zoomViewport(
      { scale: 1, offsetX: 0, offsetY: 0 },
      2,
      { x: 100, y: 80 },
    );

    expect(viewport).toEqual({ scale: 2, offsetX: -100, offsetY: -80 });
    expect(graphPointFromCanvas({ x: 40, y: 20 }, viewport)).toEqual({
      x: 70,
      y: 50,
    });
  });

  // The hit boxes are graph coordinates, so the clickable halo has to be
  // divided by the zoom to stay a constant size on screen.
  it("shrinks the clickable halo as the view zooms in", () => {
    // 5px beyond the rim, clear of the edge line: inside the 7px halo at 1x,
    // outside it at 4x.
    expect(hitTestGraph(20, 37, nodes, edges, 1)).toEqual({ kind: "node", key: "Author:1" });
    expect(hitTestGraph(20, 37, nodes, edges, 4)).toBeNull();
    expect(hitTestGraph(20, 32, nodes, edges, 4)).toEqual({ kind: "node", key: "Author:1" });
  });

  it("widens the clickable halo as the view zooms out", () => {
    expect(hitTestGraph(70, 32, nodes, edges, 1)).toBeNull();
    expect(hitTestGraph(70, 32, nodes, edges, 0.5)).toEqual({ kind: "edge", edge });
  });

  it("clamps zoom to its limits", () => {
    const viewport = { scale: 1, offsetX: 0, offsetY: 0 };
    expect(zoomViewport(viewport, 10, { x: 0, y: 0 }).scale).toBe(4);
    expect(zoomViewport(viewport, 0.1, { x: 0, y: 0 }).scale).toBe(0.25);
  });
});

describe("pan clamping", () => {
  const size = { width: 800, height: 600 };
  const origin = { scale: 1, offsetX: 0, offsetY: 0 };

  it("leaves a modest pan alone", () => {
    const panned = { ...origin, offsetX: -120, offsetY: 40 };
    expect(clampPan(panned, size)).toEqual(panned);
  });

  it("keeps part of the graph on screen however far it is dragged", () => {
    const left = clampPan({ ...origin, offsetX: -100_000 }, size);
    const right = clampPan({ ...origin, offsetX: 100_000 }, size);
    const down = clampPan({ ...origin, offsetY: 100_000 }, size);

    // Some of the layout box still overlaps the viewport in every direction.
    expect(left.offsetX + size.width).toBeGreaterThan(0);
    expect(right.offsetX).toBeLessThan(size.width);
    expect(down.offsetY).toBeLessThan(size.height);
  });

  it("accounts for the zoom when deciding what is still visible", () => {
    const zoomedOut = clampPan({ scale: 0.25, offsetX: -100_000, offsetY: 0 }, size);
    expect(zoomedOut.offsetX + size.width * 0.25).toBeGreaterThan(0);
  });

  it("does not clamp against an unmeasured canvas", () => {
    const panned = { ...origin, offsetX: -100_000 };
    expect(clampPan(panned, { width: 0, height: 0 })).toEqual(panned);
  });
});
