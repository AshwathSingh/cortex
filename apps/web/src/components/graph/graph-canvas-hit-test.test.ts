import { describe, expect, it } from "vitest";

import { hitTestGraph } from "@/components/graph/graph-canvas";
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
});
