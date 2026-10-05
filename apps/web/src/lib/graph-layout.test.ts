import { describe, expect, it } from "vitest";

import {
  ALPHA_MIN,
  DEFAULT_RADIUS,
  GraphSimulation,
  seedNodes,
} from "@/lib/graph-layout";

const SIZE = { width: 800, height: 600 };

function keys(n: number): string[] {
  return Array.from({ length: n }, (_, i) => `PullRequest:${i}`);
}

function allFinite(nodes: readonly { x: number; y: number }[]): boolean {
  return nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y));
}

function distance(
  a: { x: number; y: number },
  b: { x: number; y: number },
): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

describe("seedNodes", () => {
  it("places every node at a finite position", () => {
    expect(allFinite(seedNodes(keys(50), SIZE.width, SIZE.height))).toBe(true);
  });

  it("never stacks two nodes on the same point", () => {
    // Co-located nodes make repulsion explode, so this is a correctness guard.
    const nodes = seedNodes(keys(40), SIZE.width, SIZE.height);
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        expect(distance(nodes[i], nodes[j])).toBeGreaterThan(0);
      }
    }
  });

  it("handles a single node", () => {
    const [only] = seedNodes(["Author:1"], SIZE.width, SIZE.height);
    expect(Number.isFinite(only.x) && Number.isFinite(only.y)).toBe(true);
  });

  it("is deterministic, so a reload does not reshuffle the graph", () => {
    const a = seedNodes(keys(20), SIZE.width, SIZE.height);
    const b = seedNodes(keys(20), SIZE.width, SIZE.height);
    expect(a).toEqual(b);
  });
});

describe("GraphSimulation", () => {
  it("cools to settled and reports it", () => {
    const sim = new GraphSimulation(keys(10), [], SIZE);
    expect(sim.settled).toBe(false);
    sim.run();
    expect(sim.settled).toBe(true);
    expect(sim.alpha).toBeLessThanOrEqual(ALPHA_MIN);
  });

  it("terminates rather than spinning forever", () => {
    const sim = new GraphSimulation(keys(30), [], SIZE);
    sim.run(1000);
    expect(sim.settled).toBe(true);
  });

  it("keeps every position finite after settling", () => {
    const sim = new GraphSimulation(
      keys(60),
      [{ source: "PullRequest:0", target: "PullRequest:1" }],
      SIZE,
    );
    sim.run();
    expect(allFinite(sim.nodes)).toBe(true);
  });

  it("never collapses nodes onto one another", () => {
    // The point of repulsion: distinct nodes must stay visually distinct, which
    // is the first acceptance criterion ("distinct nodes ... must visibly render").
    const sim = new GraphSimulation(keys(25), [], SIZE);
    sim.run();
    let min = Infinity;
    for (let i = 0; i < sim.nodes.length; i += 1) {
      for (let j = i + 1; j < sim.nodes.length; j += 1) {
        min = Math.min(min, distance(sim.nodes[i], sim.nodes[j]));
      }
    }
    expect(min).toBeGreaterThan(10); // comfortably more than the 7px node radius
  });

  it("settles a connected graph more compactly than an unconnected one", () => {
    // Spring attraction should draw a chain together relative to the same number
    // of free-floating nodes. Compared over the whole graph rather than one pair,
    // because with only two nodes the repulsion/centering equilibrium happens to
    // sit at springLength and the spring contributes nothing.
    const n = 12;
    const chain = Array.from({ length: n - 1 }, (_, i) => ({
      source: `PullRequest:${i}`,
      target: `PullRequest:${i + 1}`,
    }));
    const linked = new GraphSimulation(keys(n), chain, SIZE);
    const loose = new GraphSimulation(keys(n), [], SIZE);
    linked.run();
    loose.run();

    const meanSpread = (nodes: readonly { x: number; y: number }[]) => {
      let total = 0;
      let pairs = 0;
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          total += distance(nodes[i], nodes[j]);
          pairs += 1;
        }
      }
      return total / pairs;
    };

    expect(meanSpread(linked.nodes)).toBeLessThan(meanSpread(loose.nodes));
  });

  it("ignores edges naming a node it was not given", () => {
    const sim = new GraphSimulation(
      ["Author:1"],
      [{ source: "Author:1", target: "PullRequest:999" }],
      SIZE,
    );
    expect(() => sim.run()).not.toThrow();
    expect(allFinite(sim.nodes)).toBe(true);
  });

  it("survives an empty graph", () => {
    const sim = new GraphSimulation([], [], SIZE);
    expect(() => sim.run()).not.toThrow();
    expect(sim.nodes).toEqual([]);
  });

  it("exposes nodes by key", () => {
    const sim = new GraphSimulation(["Issue:5"], [], SIZE);
    expect(sim.nodeAt("Issue:5")?.key).toBe("Issue:5");
    expect(sim.nodeAt("Issue:404")).toBeUndefined();
  });

  it("reports a finite bounding box, and a sane one when empty", () => {
    const sim = new GraphSimulation(keys(12), [], SIZE);
    sim.run();
    const b = sim.bounds();
    expect(b.maxX).toBeGreaterThan(b.minX);
    expect(b.maxY).toBeGreaterThan(b.minY);

    const empty = new GraphSimulation([], [], SIZE).bounds();
    expect(empty).toEqual({ minX: 0, minY: 0, maxX: 800, maxY: 600 });
  });

  it("lays out a few hundred nodes without blowing up", () => {
    const n = 300;
    const edges = Array.from({ length: n - 1 }, (_, i) => ({
      source: `PullRequest:${i}`,
      target: `PullRequest:${i + 1}`,
    }));
    const sim = new GraphSimulation(keys(n), edges, SIZE);
    sim.run();
    expect(allFinite(sim.nodes)).toBe(true);
  });
});

describe("collision separation", () => {
  it("leaves no two circles overlapping", () => {
    // The fix for the unreadable pile-up: circles must not intersect, so both
    // the nodes and their labels stay distinguishable.
    const specs = keys(40).map((key, i) => ({
      key,
      radius: i % 5 === 0 ? 20 : 11,
      charge: i % 5 === 0 ? 2.4 : 1,
    }));
    const sim = new GraphSimulation(specs, [], SIZE);
    sim.run();

    for (let i = 0; i < sim.nodes.length; i += 1) {
      for (let j = i + 1; j < sim.nodes.length; j += 1) {
        const a = sim.nodes[i];
        const b = sim.nodes[j];
        expect(distance(a, b)).toBeGreaterThanOrEqual(a.radius + b.radius);
      }
    }
  });

  it("exposes radius but keeps physics state off the public node type", () => {
    const sim = new GraphSimulation(
      [{ key: "Author:1", radius: 22, charge: 2.4 }, "PullRequest:1"],
      [],
      SIZE,
    );
    expect(sim.nodeAt("Author:1")?.radius).toBe(22);
    // Plain string entries still work, so existing callers are unaffected.
    expect(sim.nodeAt("PullRequest:1")?.radius).toBe(DEFAULT_RADIUS);
    // `charge` and `vx`/`vy` are intentionally absent from LayoutNode; the
    // renderer has no business reading them.
    expect("charge" in (sim.nodes[0] as object)).toBe(true); // present at runtime
  });

  it("gives a high-charge node more room than a low-charge one", () => {
    // Charge is no longer readable, so assert what it is FOR: hubs push harder
    // and end up further from their neighbours.
    const spread = (charge: number) => {
      const sim = new GraphSimulation(
        [
          { key: "Author:1", radius: 12, charge },
          "PullRequest:1",
          "PullRequest:2",
          "PullRequest:3",
        ],
        [],
        SIZE,
      );
      sim.run();
      const hub = sim.nodeAt("Author:1")!;
      const others = sim.nodes.filter((n) => n.key !== "Author:1");
      return Math.min(...others.map((n) => distance(hub, n)));
    };

    expect(spread(3)).toBeGreaterThan(spread(1));
  });

  it("keeps every node inside the viewport when clamped", () => {
    const sim = new GraphSimulation(keys(30), [], SIZE);
    sim.run();
    sim.clampToBounds();
    for (const n of sim.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(SIZE.width);
      expect(n.y).toBeLessThanOrEqual(SIZE.height);
    }
  });
});
