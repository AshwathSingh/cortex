/**
 * T-14.4: a force-directed layout, hand-rolled so the canvas has no dependency.
 *
 * Forces per tick:
 *   - repulsion between every pair of nodes (Coulomb, O(n^2)), scaled by each
 *     node's `charge` so hubs push harder and carve out their own territory
 *   - attraction along every edge (Hooke)
 *   - a weak pull toward the centre, so disconnected components don't drift off
 *   - a collision pass that separates any two nodes whose circles overlap
 *
 * The collision pass is what stops the "ball of mush": without it, nodes settle
 * on top of one another and neither the circles nor their labels are readable.
 *
 * The graph is effectively a forest of stars — a pull request has exactly one
 * author — so giving authors a much larger `charge` than their leaves makes each
 * author's work settle into its own visible cluster. That structure is the point:
 * a viewer should be able to see who owns what without reading a single label.
 *
 * `alpha` cools geometrically and the simulation reports itself settled below
 * ALPHA_MIN, so the render loop can stop instead of spinning forever.
 *
 * O(n^2) repulsion is deliberate. Design issue 3.a.vii sizes this for hundreds
 * of nodes; at n=500 that is 125k pair calculations per tick, which is fine, and
 * a quadtree would be unjustified complexity here. The node ceiling lives in
 * `app/graph/queries.py` (DEFAULT_NODE_LIMIT).
 *
 * Positions are seeded deterministically from the node key, NOT Math.random, so
 * a given graph always lays out the same way — reloading doesn't reshuffle it,
 * and tests are reproducible.
 */

export type NodeSpec = {
  key: string;
  /** Drawn radius, in px. Also drives collision separation. */
  radius?: number;
  /** Repulsion weight. Hubs use a high value to claim space. */
  charge?: number;
};

/**
 * What the renderer sees: where to draw a node and how big. Velocity, charge and
 * everything else the integrator mutates stay on `SimulationNode` below, so a
 * consumer cannot accidentally depend on (or corrupt) the physics state.
 */
export type LayoutNode = {
  readonly key: string;
  readonly x: number;
  readonly y: number;
  readonly radius: number;
};

/** Internal: a node plus the mutable state the integrator needs. */
export type SimulationNode = LayoutNode & {
  x: number;
  y: number;
  vx: number;
  vy: number;
  charge: number;
};

export type LayoutEdge = { source: string; target: string };

export type SimulationOptions = {
  width: number;
  height: number;
  repulsion?: number;
  springLength?: number;
  springStrength?: number;
  centering?: number;
  damping?: number;
  /** Extra gap enforced between node circles, in px. */
  collisionPadding?: number;
};

const ALPHA_START = 1;
const ALPHA_DECAY = 0.978;
export const ALPHA_MIN = 0.02;

export const DEFAULT_RADIUS = 10;

const DEFAULTS = {
  repulsion: 16000,
  springLength: 130,
  springStrength: 0.045,
  centering: 0.02,
  damping: 0.84,
  collisionPadding: 26,
};

/** Deterministic 32-bit hash, so seeding depends on identity not call order. */
function hashKey(key: string): number {
  let hash = 2166136261;
  for (let i = 0; i < key.length; i += 1) {
    hash ^= key.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function toSpec(node: string | NodeSpec): Required<NodeSpec> {
  if (typeof node === "string") {
    return { key: node, radius: DEFAULT_RADIUS, charge: 1 };
  }
  return {
    key: node.key,
    radius: node.radius ?? DEFAULT_RADIUS,
    charge: node.charge ?? 1,
  };
}

/**
 * Seed nodes on a phyllotaxis spiral around the centre. Spreading them before
 * the first tick matters: co-located nodes produce a near-infinite repulsion
 * impulse and the layout explodes.
 */
export function seedNodes(
  nodes: readonly (string | NodeSpec)[],
  width: number,
  height: number,
): SimulationNode[] {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) / 2.2;

  // Seed position depends on index, so the caller's ordering would otherwise
  // decide the layout. Sorting by key makes the result identical no matter what
  // order the API returned -- the same graph lays out the same way every reload.
  const ordered = [...nodes].map(toSpec).sort((a, b) => a.key.localeCompare(b.key));

  return ordered.map((spec, index) => {
    const t = ordered.length > 1 ? index / (ordered.length - 1) : 0;
    // Golden angle keeps successive nodes apart instead of forming spokes.
    const angle = index * 2.39996 + (hashKey(spec.key) % 360) * (Math.PI / 180) * 0.15;
    const r = radius * Math.sqrt(t) || radius * 0.1;
    return {
      key: spec.key,
      x: cx + Math.cos(angle) * r,
      y: cy + Math.sin(angle) * r,
      vx: 0,
      vy: 0,
      radius: spec.radius,
      charge: spec.charge,
    };
  });
}

export class GraphSimulation {
  /** Exposed as position data only; the objects carry physics state internally. */
  readonly nodes: readonly LayoutNode[];
  private readonly sim: SimulationNode[];
  private readonly index: Map<string, SimulationNode>;
  private readonly edges: LayoutEdge[];
  private readonly opts: Required<SimulationOptions>;
  private alphaValue = ALPHA_START;

  constructor(
    nodes: readonly (string | NodeSpec)[],
    edges: readonly LayoutEdge[],
    options: SimulationOptions,
  ) {
    this.opts = { ...DEFAULTS, ...options };
    this.sim = seedNodes(nodes, this.opts.width, this.opts.height);
    this.nodes = this.sim;
    this.index = new Map(this.sim.map((node) => [node.key, node]));
    // Drop edges naming a node we weren't given, so a malformed payload can't
    // crash the render loop. The API already filters these; belt and braces.
    this.edges = edges.filter(
      (edge) => this.index.has(edge.source) && this.index.has(edge.target),
    );
  }

  get alpha(): number {
    return this.alphaValue;
  }

  get settled(): boolean {
    return this.alphaValue <= ALPHA_MIN;
  }

  nodeAt(key: string): LayoutNode | undefined {
    return this.index.get(key);
  }

  /** Advance one frame. Returns the node list for convenience. */
  tick(): readonly LayoutNode[] {
    const { repulsion, springLength, springStrength, centering, damping } = this.opts;
    const cx = this.opts.width / 2;
    const cy = this.opts.height / 2;
    const a = this.alphaValue;
    const nodes = this.sim;

    for (let i = 0; i < nodes.length; i += 1) {
      const node = nodes[i];
      let fx = (cx - node.x) * centering;
      let fy = (cy - node.y) * centering;

      for (let j = 0; j < nodes.length; j += 1) {
        if (i === j) continue;
        const other = nodes[j];
        let dx = node.x - other.x;
        let dy = node.y - other.y;
        let distSq = dx * dx + dy * dy;
        if (distSq < 0.01) {
          // Exactly coincident: nudge apart deterministically rather than
          // dividing by ~zero and flinging the pair to infinity.
          dx = ((hashKey(node.key) % 17) - 8) * 0.1 || 0.1;
          dy = ((hashKey(other.key) % 17) - 8) * 0.1 || 0.1;
          distSq = dx * dx + dy * dy;
        }
        // Both charges count, so hub-to-hub repels hardest and clusters separate.
        const force = (repulsion * node.charge * other.charge) / distSq;
        const dist = Math.sqrt(distSq);
        fx += (dx / dist) * force;
        fy += (dy / dist) * force;
      }

      node.vx = (node.vx + fx * a) * damping;
      node.vy = (node.vy + fy * a) * damping;
    }

    for (const edge of this.edges) {
      const source = this.index.get(edge.source)!;
      const target = this.index.get(edge.target)!;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const pull = (dist - springLength) * springStrength * a;
      const ux = (dx / dist) * pull;
      const uy = (dy / dist) * pull;
      source.vx += ux;
      source.vy += uy;
      target.vx -= ux;
      target.vy -= uy;
    }

    for (const node of nodes) {
      node.x += node.vx;
      node.y += node.vy;
    }

    this.separate();
    this.alphaValue *= ALPHA_DECAY;
    return nodes;
  }

  /**
   * Push apart any two circles that overlap. Runs on positions rather than
   * velocities so a hard overlap is resolved immediately, which is what keeps
   * nodes and their labels readable.
   */
  private separate(): void {
    const pad = this.opts.collisionPadding;
    const nodes = this.sim;
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const minDist = a.radius + b.radius + pad;
        const distSq = dx * dx + dy * dy;
        if (distSq >= minDist * minDist || distSq === 0) continue;
        const dist = Math.sqrt(distSq) || 0.01;
        const shift = (minDist - dist) / 2;
        const ux = (dx / dist) * shift;
        const uy = (dy / dist) * shift;
        a.x -= ux;
        a.y -= uy;
        b.x += ux;
        b.y += uy;
      }
    }
  }

  /** Keep every node inside the viewport, accounting for its radius. */
  clampToBounds(margin = 8): void {
    const { width, height } = this.opts;
    for (const node of this.sim) {
      const r = node.radius + margin;
      node.x = Math.min(width - r, Math.max(r, node.x));
      node.y = Math.min(height - r, Math.max(r, node.y));
    }
  }

  /** Run to settled without rendering. Used for tests and for a static image. */
  run(maxTicks = 500): readonly LayoutNode[] {
    let ticks = 0;
    while (!this.settled && ticks < maxTicks) {
      this.tick();
      ticks += 1;
    }
    return this.nodes;
  }

  /** Bounding box of the laid-out nodes, for fitting the view. */
  bounds(): { minX: number; minY: number; maxX: number; maxY: number } {
    if (this.nodes.length === 0) {
      return { minX: 0, minY: 0, maxX: this.opts.width, maxY: this.opts.height };
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const node of this.sim) {
      if (node.x < minX) minX = node.x;
      if (node.y < minY) minY = node.y;
      if (node.x > maxX) maxX = node.x;
      if (node.y > maxY) maxY = node.y;
    }
    return { minX, minY, maxX, maxY };
  }
}
