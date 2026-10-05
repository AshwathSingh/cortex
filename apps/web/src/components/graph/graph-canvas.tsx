"use client";

import { useEffect, useRef, useState } from "react";

import { GraphSimulation, type NodeSpec } from "@/lib/graph-layout";
import type { GraphEdge, GraphNode, GraphNodeType } from "@/lib/api-types";

/**
 * Canvas-based, not SVG, per design issue 3.a.vii: hundreds of nodes means
 * hundreds of DOM elements under SVG, and the layout thrash dominates. One
 * <canvas> and a requestAnimationFrame loop keeps it to a single element.
 *
 * Readability rules, in order of how much they matter:
 *   1. Authors are hubs — drawn large, repelling hard, so each author's work
 *      forms a visible cluster. The graph is a forest of stars (a pull request
 *      has one author), and showing that is the whole point of the view.
 *   2. Every type has a SHAPE as well as a colour. Roughly one in twelve men has
 *      some red/green deficiency, and a canvas has no text alternative to fall
 *      back on, so hue alone would make the legend useless to them.
 *   3. Circles never overlap (the simulation's collision pass guarantees it).
 *   4. A label is only drawn if its box clears every label already drawn, so
 *      text never stacks. Hubs get first claim.
 */

/** Node geometry. The shape is the accessible, non-colour channel. */
export type NodeShape = "circle" | "square" | "diamond";

export const NODE_SHAPES: Record<GraphNodeType, NodeShape> = {
  Author: "circle",
  PullRequest: "square",
  Issue: "diamond",
};

const FALLBACK_SHAPE: NodeShape = "circle";

export function nodeShape(type: string): NodeShape {
  return NODE_SHAPES[type as GraphNodeType] ?? FALLBACK_SHAPE;
}

/**
 * Colours live in globals.css so the graph restyles with the rest of the app.
 * Canvas cannot resolve `var(...)` through ctx.fillStyle, so each token is read
 * off the element once per effect; the fallbacks keep the graph drawable if the
 * stylesheet has not applied yet (or in jsdom, which computes nothing).
 */
const GRAPH_TOKENS = {
  Author: ["--cortex-graph-author", "#78a0ff"],
  PullRequest: ["--cortex-graph-pull-request", "#7ddfa0"],
  Issue: ["--cortex-graph-issue", "#e0a86a"],
  unknown: ["--cortex-graph-node-unknown", "#a4adbd"],
  edge: ["--cortex-graph-edge", "rgba(120, 160, 255, 0.22)"],
  edgeHub: ["--cortex-graph-edge-hub", "rgba(120, 160, 255, 0.38)"],
  label: ["--cortex-graph-label", "#c7cedd"],
  labelDim: ["--cortex-graph-label-dim", "#8b94a6"],
} as const satisfies Record<string, readonly [string, string]>;

type Palette = Record<keyof typeof GRAPH_TOKENS, string>;

function readPalette(el: Element): Palette {
  const style =
    typeof window !== "undefined" && window.getComputedStyle
      ? window.getComputedStyle(el)
      : null;
  const out = {} as Palette;
  for (const [name, [token, fallback]] of Object.entries(GRAPH_TOKENS)) {
    const value = style?.getPropertyValue(token).trim();
    out[name as keyof Palette] = value || fallback;
  }
  return out;
}

/** Hubs read as hubs at a glance; leaves stay secondary but still clickable-size. */
const AUTHOR_RADIUS = 19;
const LEAF_RADIUS = 11;
/** Each extra authored item widens the hub a little, up to a cap. */
const AUTHOR_GROWTH = 1.1;
const AUTHOR_MAX_RADIUS = 30;

const LABEL_FONT = 12;
const LABEL_LINE_HEIGHT = 15;

/** Ring outline weight, and the centre dot as a fraction of the node radius. */
const RING_WIDTH = 2;
const CORE_RATIO = 0.34;
/** Barely-there fill inside the ring, so the node still reads as a target. */
const HALO_ALPHA = 0.14;

/** `#rrggbb` -> `rgba(r, g, b, a)`; other formats are returned unchanged. */
function withAlpha(colour: string, alpha: number): string {
  const hex = colour.trim();
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex;
  const value = hex.slice(1);
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Trace a node outline. Squares and diamonds use the radius as a half-extent. */
function tracePath(
  ctx: CanvasRenderingContext2D,
  shape: NodeShape,
  x: number,
  y: number,
  r: number,
): void {
  ctx.beginPath();
  if (shape === "circle") {
    ctx.arc(x, y, r, 0, Math.PI * 2);
    return;
  }
  if (shape === "square") {
    // Trimmed so a square does not read as heavier than a circle of equal r.
    const h = r * 0.88;
    ctx.rect(x - h, y - h, h * 2, h * 2);
    return;
  }
  const d = r * 1.18; // diamonds look small at equal radius, so bias them up
  ctx.moveTo(x, y - d);
  ctx.lineTo(x + d, y);
  ctx.lineTo(x, y + d);
  ctx.lineTo(x - d, y);
  ctx.closePath();
}

type Box = { x1: number; y1: number; x2: number; y2: number };

function overlaps(a: Box, b: Box): boolean {
  return !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

type GraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  height?: number;
};

export function GraphCanvas({ nodes, edges, height = 560 }: GraphCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frameRef = useRef<number | null>(null);
  const [width, setWidth] = useState<number>(() => 0);

  // Track the container's width rather than measuring once on mount: the panel
  // reflows when a sidebar opens or the window resizes, and a canvas that keeps
  // its original backing-store width would stretch and blur.
  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!parent) return;

    const measure = () => setWidth(parent.clientWidth || 960);
    measure();

    if (typeof ResizeObserver === "undefined") return; // jsdom, older browsers
    const observer = new ResizeObserver(measure);
    observer.observe(parent);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || width <= 0) return;
    const maybeContext = canvas.getContext("2d");
    if (!maybeContext) return; // jsdom without a 2d context, or a very old browser
    // Re-bind as non-nullable: TypeScript drops the null-narrowing inside the
    // draw/frame closures below, which are defined after this guard.
    const ctx: CanvasRenderingContext2D = maybeContext;

    const palette = readPalette(canvas);
    const colourOf = (type: string): string =>
      palette[type as keyof Palette] ?? palette.unknown;

    // The backing store is a whole number of device pixels, and the transform
    // uses the scale that ACTUALLY results, not the raw ratio. On a fractional
    // DPR (1.25 and 1.5 are common on Windows) `round(w * ratio)` disagrees with
    // `ratio`, and every stroke lands a fraction of a pixel off.
    const ratio =
      typeof window !== "undefined" && window.devicePixelRatio
        ? window.devicePixelRatio
        : 1;
    const deviceWidth = Math.round(width * ratio);
    const deviceHeight = Math.round(height * ratio);
    canvas.width = deviceWidth;
    canvas.height = deviceHeight;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(deviceWidth / width, 0, 0, deviceHeight / height, 0, 0);

    // Canvas `font` is parsed as CSS but does NOT resolve custom properties —
    // `12px var(--font-geist-sans)` is invalid, so the assignment is silently
    // ignored and every label falls back to the default 10px sans-serif.
    const resolvedFamily =
      (typeof window !== "undefined" && window.getComputedStyle
        ? window.getComputedStyle(canvas).fontFamily
        : "") || "system-ui, sans-serif";

    const byKey = new Map(nodes.map((node) => [node.key, node]));

    // Degree drives hub size: an author with ten pull requests should dominate
    // one with a single fix.
    const degree = new Map<string, number>();
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }

    const radiusOf = (node: GraphNode): number => {
      if (node.type !== "Author") return LEAF_RADIUS;
      const grown = AUTHOR_RADIUS + (degree.get(node.key) ?? 0) * AUTHOR_GROWTH;
      return Math.min(AUTHOR_MAX_RADIUS, grown);
    };

    const specs: NodeSpec[] = nodes.map((node) => ({
      key: node.key,
      radius: radiusOf(node),
      // Hubs claim territory so clusters separate instead of blending.
      charge: node.type === "Author" ? 2.4 : 1,
    }));

    const simulation = new GraphSimulation(specs, edges, { width, height });

    // Hubs first: they get first claim on label space.
    const drawOrder = [...simulation.nodes].sort(
      (a, b) => b.radius - a.radius || a.key.localeCompare(b.key),
    );

    function draw() {
      ctx.clearRect(0, 0, width, height);

      for (const edge of edges) {
        const source = simulation.nodeAt(edge.source);
        const target = simulation.nodeAt(edge.target);
        if (!source || !target) continue;
        // Edges touching a hub are slightly brighter, so spokes read as spokes.
        const hub = Math.max(source.radius, target.radius) > LEAF_RADIUS;
        ctx.strokeStyle = hub ? palette.edgeHub : palette.edge;
        ctx.lineWidth = hub ? 1.4 : 1;
        ctx.beginPath();
        ctx.moveTo(source.x, source.y);
        ctx.lineTo(target.x, target.y);
        ctx.stroke();
      }

      // Leaves first, hubs last, so a hub is never hidden behind its own spokes.
      for (let i = drawOrder.length - 1; i >= 0; i -= 1) {
        const placed = drawOrder[i];
        const node = byKey.get(placed.key);
        const colour = colourOf(node?.type ?? "unknown");
        const shape = nodeShape(node?.type ?? "");
        const r = placed.radius;

        // Outline + centre mark, not a solid blob: the shape is what carries the
        // type for anyone who cannot rely on the hue, so it has to stay legible.
        tracePath(ctx, shape, placed.x, placed.y, r);
        ctx.fillStyle = withAlpha(colour, HALO_ALPHA);
        ctx.fill();

        tracePath(ctx, shape, placed.x, placed.y, r);
        ctx.lineWidth = RING_WIDTH;
        ctx.strokeStyle = colour;
        ctx.stroke();

        tracePath(ctx, shape, placed.x, placed.y, Math.max(2.5, r * CORE_RATIO));
        ctx.fillStyle = colour;
        ctx.fill();
      }

      // Labels last, with collision avoidance: a label is skipped entirely
      // rather than drawn on top of another. This is what stops the pile-up.
      ctx.font = `${LABEL_FONT}px ${resolvedFamily}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const claimed: Box[] = [];

      for (const placed of drawOrder) {
        const node = byKey.get(placed.key);
        if (!node) continue;
        const isHub = node.type === "Author";
        const text = truncate(node.title, isHub ? 22 : 26);
        const textWidth = ctx.measureText(text).width;
        // Text drawn at a fractional coordinate is resampled across two pixel
        // columns. Node positions are floats, so snap the label.
        const cx = Math.round(placed.x);
        const top = Math.round(placed.y + placed.radius + 7);
        const box: Box = {
          x1: cx - textWidth / 2 - 3,
          y1: top - 2,
          x2: cx + textWidth / 2 + 3,
          y2: top + LABEL_LINE_HEIGHT,
        };
        if (claimed.some((other) => overlaps(box, other))) continue;
        claimed.push(box);
        ctx.fillStyle = isHub ? palette.label : palette.labelDim;
        ctx.fillText(text, cx, top);
      }
    }

    function frame() {
      simulation.tick();
      simulation.clampToBounds();
      draw();
      // Stop once cooled: an idle rAF loop burns battery for no visual change.
      if (!simulation.settled) {
        frameRef.current = requestAnimationFrame(frame);
      }
    }

    // Draw the seeded positions immediately, so something is on screen even if
    // rAF never fires (jsdom, reduced-motion, a backgrounded tab).
    draw();
    if (typeof requestAnimationFrame === "function") {
      frameRef.current = requestAnimationFrame(frame);
    } else {
      simulation.run();
      simulation.clampToBounds();
      draw();
    }

    return () => {
      if (frameRef.current !== null && typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(frameRef.current);
      }
      frameRef.current = null;
    };
  }, [nodes, edges, height, width]);

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={`Knowledge graph: ${nodes.length} nodes, ${edges.length} connections`}
      className="block w-full rounded-panel border border-border/50 bg-surface/40"
      style={{ height }}
    />
  );
}
