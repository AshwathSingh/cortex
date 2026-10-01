"use client";

import { useEffect, useRef } from "react";

import { GraphSimulation, type NodeSpec } from "@/lib/graph-layout";
import type { GraphEdge, GraphNode, GraphNodeType } from "@/lib/api-types";

/**
 * Canvas-based, not SVG, per design issue 3.a.vii: hundreds of nodes means
 * hundreds of DOM elements under SVG, and the layout thrash dominates. One
 * <canvas> and a requestAnimationFrame loop keeps it to a single element.
 *
 * Readability rules, in order of how much they matter:
 *   1. Authors are hubs — drawn large, repelling hard, so each author's work
 *      forms a visible cluster. The graph is a forest of stars (a PR has one
 *      author), and showing that is the whole point of the view.
 *   2. Circles never overlap (the simulation's collision pass guarantees it).
 *   3. A label is only drawn if its box clears every label already drawn, so
 *      text never stacks. Hubs get first claim, so the names you most need stay.
 */

/** Only the three labels that actually exist in the graph today. */
export const NODE_COLOURS: Record<GraphNodeType, string> = {
  Author: "#78a0ff",
  PullRequest: "#7ddfa0",
  Issue: "#e0a86a",
};

const FALLBACK_COLOUR = "#a4adbd";

/** Hubs read as hubs at a glance; leaves stay secondary but still clickable-size. */
const AUTHOR_RADIUS = 19;
const LEAF_RADIUS = 11;
/** Each extra authored item widens the hub a little, up to a cap. */
const AUTHOR_GROWTH = 1.1;
const AUTHOR_MAX_RADIUS = 30;

const EDGE_COLOUR = "rgba(120, 160, 255, 0.22)";
const EDGE_COLOUR_HUB = "rgba(120, 160, 255, 0.38)";
const LABEL_COLOUR = "#c7cedd";
const LABEL_COLOUR_DIM = "#8b94a6";
const LABEL_FONT = 12;
const LABEL_LINE_HEIGHT = 15;

/** Ring outline weight, and the centre dot as a fraction of the node radius. */
const RING_WIDTH = 2;
const CORE_RATIO = 0.34;
/** Barely-there fill inside the ring, so the node still reads as a target. */
const HALO_ALPHA = 0.14;

export function nodeColour(type: string): string {
  return NODE_COLOURS[type as GraphNodeType] ?? FALLBACK_COLOUR;
}

/** `#rrggbb` -> `rgba(r, g, b, a)`. Node colours are all hex literals above. */
function withAlpha(hex: string, alpha: number): string {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
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

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const maybeContext = canvas.getContext("2d");
    if (!maybeContext) return; // jsdom without a 2d context, or a very old browser
    // Re-bind as non-nullable: TypeScript drops the null-narrowing inside the
    // draw/frame closures below, which are defined after this guard.
    const ctx: CanvasRenderingContext2D = maybeContext;

    const parentWidth = canvas.parentElement?.clientWidth;
    const width = parentWidth && parentWidth > 0 ? parentWidth : 960;
    // Render at device resolution so the graph isn't blurry on a HiDPI screen,
    // while CSS keeps it at logical size.
    const ratio =
      typeof window !== "undefined" && window.devicePixelRatio
        ? window.devicePixelRatio
        : 1;
    // Blur fix 1: the backing store is a whole number of device pixels, and the
    // transform uses the scale that ACTUALLY results, not the raw ratio. On a
    // fractional DPR (1.25 and 1.5 are common on Windows) `floor(w * ratio)`
    // disagrees with `ratio`, and every stroke lands a fraction of a pixel off.
    const deviceWidth = Math.round(width * ratio);
    const deviceHeight = Math.round(height * ratio);
    canvas.width = deviceWidth;
    canvas.height = deviceHeight;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(deviceWidth / width, 0, 0, deviceHeight / height, 0, 0);

    // Blur fix 2: canvas `font` is parsed as CSS, but it does NOT resolve
    // custom properties — `12px var(--font-geist-sans)` is invalid, so the
    // assignment was silently ignored and every label fell back to the default
    // 10px sans-serif. Resolve the family off the element instead.
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
        ctx.strokeStyle = hub ? EDGE_COLOUR_HUB : EDGE_COLOUR;
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
        const colour = nodeColour(node?.type ?? "");
        const r = placed.radius;

        // Ring + centre dot, not a solid disc: the outline reads as a distinct
        // object at any size, and the hollow middle lets edges pass behind
        // without the node looking like a blob.
        ctx.beginPath();
        ctx.arc(placed.x, placed.y, r, 0, Math.PI * 2);
        ctx.fillStyle = withAlpha(colour, HALO_ALPHA);
        ctx.fill();

        ctx.beginPath();
        ctx.arc(placed.x, placed.y, r, 0, Math.PI * 2);
        ctx.lineWidth = RING_WIDTH;
        ctx.strokeStyle = colour;
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(placed.x, placed.y, Math.max(2.5, r * CORE_RATIO), 0, Math.PI * 2);
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
        // Blur fix 3: text drawn at a fractional coordinate is resampled across
        // two pixel columns. Node positions are floats, so snap the label.
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
        ctx.fillStyle = isHub ? LABEL_COLOUR : LABEL_COLOUR_DIM;
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
  }, [nodes, edges, height]);

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
