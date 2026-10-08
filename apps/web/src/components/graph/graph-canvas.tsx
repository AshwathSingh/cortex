"use client";

import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type WheelEvent,
} from "react";

import type { GraphEdge, GraphNode, GraphNodeType, GraphSelection } from "@/lib/api-types";
import { GraphSimulation, type NodeSpec } from "@/lib/graph-layout";

/** Fallbacks keep canvas rendering deterministic when CSS variables are unavailable. */
export const NODE_COLOURS: Record<GraphNodeType, string> = {
  Author: "#78a0ff",
  PullRequest: "#7ddfa0",
  Issue: "#e0a86a",
};

export type NodeShape = "circle" | "square" | "diamond";

export const NODE_SHAPES: Record<GraphNodeType, NodeShape> = {
  Author: "circle",
  PullRequest: "square",
  Issue: "diamond",
};

const FALLBACK_COLOUR = "#a4adbd";
const FALLBACK_SHAPE: NodeShape = "circle";
const AUTHOR_RADIUS = 19;
const LEAF_RADIUS = 11;
const AUTHOR_GROWTH = 1.1;
const AUTHOR_MAX_RADIUS = 30;
const LABEL_FONT = 12;
const LABEL_LINE_HEIGHT = 15;
const RING_WIDTH = 2;
const CORE_RATIO = 0.34;
const HALO_ALPHA = 0.14;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2.5;
const ZOOM_STEP = 1.2;
const DRAG_THRESHOLD = 3;

type Box = { x1: number; y1: number; x2: number; y2: number };
type Point = { x: number; y: number };
export type GraphViewport = {
  scale: number;
  offsetX: number;
  offsetY: number;
};
type GraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  height?: number;
  onSelectionChange?: (selection: GraphSelection) => void;
};

type HitNode = { key: string; x: number; y: number; radius: number };
type HitEdge = { edge: GraphEdge; x1: number; y1: number; x2: number; y2: number };
type PanGesture = {
  pointerId: number;
  start: Point;
  offsetX: number;
  offsetY: number;
};

const DEFAULT_VIEWPORT: GraphViewport = { scale: 1, offsetX: 0, offsetY: 0 };

function clampZoom(scale: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, scale));
}

export function zoomViewport(
  viewport: GraphViewport,
  requestedScale: number,
  anchor: Point,
): GraphViewport {
  const scale = clampZoom(requestedScale);
  const ratio = scale / viewport.scale;
  return {
    scale,
    offsetX: anchor.x - (anchor.x - viewport.offsetX) * ratio,
    offsetY: anchor.y - (anchor.y - viewport.offsetY) * ratio,
  };
}

export function graphPointFromCanvas(
  point: Point,
  viewport: GraphViewport,
): Point {
  return {
    x: (point.x - viewport.offsetX) / viewport.scale,
    y: (point.y - viewport.offsetY) / viewport.scale,
  };
}

function canvasPoint(
  canvas: HTMLCanvasElement,
  clientX: number,
  clientY: number,
): Point {
  const rect = canvas.getBoundingClientRect();
  const width =
    canvas.clientWidth || rect.width || Number.parseFloat(canvas.style.width) || 1;
  const height =
    canvas.clientHeight || rect.height || Number.parseFloat(canvas.style.height) || 1;
  return {
    x: (clientX - rect.left) * (width / (rect.width || width)),
    y: (clientY - rect.top) * (height / (rect.height || height)),
  };
}

export function hitTestGraph(
  x: number,
  y: number,
  nodes: readonly HitNode[],
  edges: readonly HitEdge[],
): GraphSelection {
  let nearestNode: HitNode | null = null;
  let nearestNodeDistance = Number.POSITIVE_INFINITY;
  for (const node of nodes) {
    const distance = Math.hypot(x - node.x, y - node.y);
    if (distance <= node.radius + 7 && distance < nearestNodeDistance) {
      nearestNode = node;
      nearestNodeDistance = distance;
    }
  }
  if (nearestNode) return { kind: "node", key: nearestNode.key };

  let nearestEdge: HitEdge | null = null;
  let nearestEdgeDistance = Number.POSITIVE_INFINITY;
  for (const edge of edges) {
    const dx = edge.x2 - edge.x1;
    const dy = edge.y2 - edge.y1;
    const lengthSquared = dx * dx + dy * dy;
    const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1,
      ((x - edge.x1) * dx + (y - edge.y1) * dy) / lengthSquared));
    const distance = Math.hypot(x - (edge.x1 + t * dx), y - (edge.y1 + t * dy));
    if (distance <= 8 && distance < nearestEdgeDistance) {
      nearestEdge = edge;
      nearestEdgeDistance = distance;
    }
  }
  return nearestEdge ? { kind: "edge", edge: nearestEdge.edge } : null;
}

export function nodeColour(type: string): string {
  return NODE_COLOURS[type as GraphNodeType] ?? FALLBACK_COLOUR;
}

export function nodeShape(type: string): NodeShape {
  return NODE_SHAPES[type as GraphNodeType] ?? FALLBACK_SHAPE;
}

function cssValue(
  styles: CSSStyleDeclaration | null,
  property: string,
  fallback: string,
): string {
  return styles?.getPropertyValue(property).trim() || fallback;
}

function withAlpha(colour: string, alpha: number): string {
  const hex = colour.trim();
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex;
  const value = hex.slice(1);
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function tracePath(
  ctx: CanvasRenderingContext2D,
  shape: NodeShape,
  x: number,
  y: number,
  radius: number,
) {
  ctx.beginPath();
  if (shape === "circle") {
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    return;
  }
  if (shape === "square") {
    const halfExtent = radius * 0.88;
    ctx.rect(
      x - halfExtent,
      y - halfExtent,
      halfExtent * 2,
      halfExtent * 2,
    );
    return;
  }
  const diamondExtent = radius * 1.18;
  ctx.moveTo(x, y - diamondExtent);
  ctx.lineTo(x + diamondExtent, y);
  ctx.lineTo(x, y + diamondExtent);
  ctx.lineTo(x - diamondExtent, y);
  ctx.closePath();
}

function overlaps(a: Box, b: Box): boolean {
  return !(a.x2 < b.x1 || a.x1 > b.x2 || a.y2 < b.y1 || a.y1 > b.y2);
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function GraphCanvas({
  nodes,
  edges,
  height = 560,
  onSelectionChange,
}: GraphCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const frameRef = useRef<number | null>(null);
  const hitNodesRef = useRef<HitNode[]>([]);
  const hitEdgesRef = useRef<HitEdge[]>([]);
  const selectionHandlerRef = useRef(onSelectionChange);
  const viewportRef = useRef<GraphViewport>(DEFAULT_VIEWPORT);
  const redrawRef = useRef<(() => void) | null>(null);
  const panRef = useRef<PanGesture | null>(null);
  const didDragRef = useRef(false);
  const [zoomPercent, setZoomPercent] = useState(100);

  useEffect(() => {
    selectionHandlerRef.current = onSelectionChange;
  }, [onSelectionChange]);

  useEffect(() => {
    const maybeCanvas = canvasRef.current;
    const maybeParent = maybeCanvas?.parentElement;
    if (!maybeCanvas || !maybeParent) return;
    const canvas: HTMLCanvasElement = maybeCanvas;
    const parent: HTMLElement = maybeParent;

    const maybeContext = canvas.getContext("2d");
    if (!maybeContext) return;
    const ctx: CanvasRenderingContext2D = maybeContext;
    let resizeObserver: ResizeObserver | null = null;
    let disposed = false;

    function cancelFrame() {
      if (frameRef.current !== null && typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(frameRef.current);
      }
      frameRef.current = null;
    }

    function renderGraph() {
      if (disposed) return;
      cancelFrame();

      const parentRect = parent.getBoundingClientRect();
      const width = Math.max(1, Math.round(parent.clientWidth || parentRect.width || 960));
      const measuredHeight = Math.max(
        1,
        Math.round(parent.clientHeight || parentRect.height || height),
      );
      const ratio = window.devicePixelRatio || 1;
      const deviceWidth = Math.round(width * ratio);
      const deviceHeight = Math.round(measuredHeight * ratio);
      const deviceScaleX = deviceWidth / width;
      const deviceScaleY = deviceHeight / measuredHeight;

      canvas.width = deviceWidth;
      canvas.height = deviceHeight;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${measuredHeight}px`;
      ctx.setTransform(
        deviceScaleX,
        0,
        0,
        deviceScaleY,
        0,
        0,
      );

      const styles = window.getComputedStyle(canvas);
      const resolvedFamily = styles.fontFamily || "system-ui, sans-serif";
      const colours: Record<GraphNodeType, string> = {
        Author: cssValue(styles, "--cortex-graph-author", NODE_COLOURS.Author),
        PullRequest: cssValue(
          styles,
          "--cortex-graph-pull-request",
          NODE_COLOURS.PullRequest,
        ),
        Issue: cssValue(styles, "--cortex-graph-issue", NODE_COLOURS.Issue),
      };
      const edgeColour = cssValue(
        styles,
        "--cortex-graph-edge",
        "rgba(120, 160, 255, 0.22)",
      );
      const hubEdgeColour = cssValue(
        styles,
        "--cortex-graph-edge-hub",
        "rgba(120, 160, 255, 0.38)",
      );
      const labelColour = cssValue(styles, "--cortex-graph-label", "#c7cedd");
      const dimLabelColour = cssValue(
        styles,
        "--cortex-graph-label-dim",
        "#8b94a6",
      );
      const byKey = new Map(nodes.map((node) => [node.key, node]));

      const degree = new Map<string, number>();
      for (const edge of edges) {
        degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
        degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
      }

      const radiusOf = (node: GraphNode): number => {
        if (node.type !== "Author") return LEAF_RADIUS;
        return Math.min(
          AUTHOR_MAX_RADIUS,
          AUTHOR_RADIUS + (degree.get(node.key) ?? 0) * AUTHOR_GROWTH,
        );
      };
      const specs: NodeSpec[] = nodes.map((node) => ({
        key: node.key,
        radius: radiusOf(node),
        charge: node.type === "Author" ? 2.4 : 1,
      }));
      const simulation = new GraphSimulation(specs, edges, {
        width,
        height: measuredHeight,
      });
      const drawOrder = [...simulation.nodes].sort(
        (a, b) => b.radius - a.radius || a.key.localeCompare(b.key),
      );

      function draw() {
        ctx.setTransform(deviceScaleX, 0, 0, deviceScaleY, 0, 0);
        ctx.clearRect(0, 0, width, measuredHeight);
        ctx.save();
        const viewport = viewportRef.current;
        ctx.translate(viewport.offsetX, viewport.offsetY);
        ctx.scale(viewport.scale, viewport.scale);

        hitNodesRef.current = simulation.nodes.map(({ key, x, y, radius }) => ({
          key, x, y, radius,
        }));
        hitEdgesRef.current = edges.flatMap((edge) => {
          const source = simulation.nodeAt(edge.source);
          const target = simulation.nodeAt(edge.target);
          return source && target
            ? [{ edge, x1: source.x, y1: source.y, x2: target.x, y2: target.y }]
            : [];
        });

        for (const edge of edges) {
          const source = simulation.nodeAt(edge.source);
          const target = simulation.nodeAt(edge.target);
          if (!source || !target) continue;
          const hub = Math.max(source.radius, target.radius) > LEAF_RADIUS;
          ctx.strokeStyle = hub ? hubEdgeColour : edgeColour;
          ctx.lineWidth = hub ? 1.4 : 1;
          ctx.beginPath();
          ctx.moveTo(source.x, source.y);
          ctx.lineTo(target.x, target.y);
          ctx.stroke();
        }

        for (let i = drawOrder.length - 1; i >= 0; i -= 1) {
          const placed = drawOrder[i];
          const node = byKey.get(placed.key);
          const colour = node ? colours[node.type] : FALLBACK_COLOUR;
          const shape = nodeShape(node?.type ?? "");

          tracePath(ctx, shape, placed.x, placed.y, placed.radius);
          ctx.fillStyle = withAlpha(colour, HALO_ALPHA);
          ctx.fill();

          tracePath(ctx, shape, placed.x, placed.y, placed.radius);
          ctx.lineWidth = RING_WIDTH;
          ctx.strokeStyle = colour;
          ctx.stroke();

          tracePath(
            ctx,
            shape,
            placed.x,
            placed.y,
            Math.max(2.5, placed.radius * CORE_RATIO),
          );
          ctx.fillStyle = colour;
          ctx.fill();
        }

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
          ctx.fillStyle = isHub ? labelColour : dimLabelColour;
          ctx.fillText(text, cx, top);
        }
        ctx.restore();
      }

      redrawRef.current = draw;

      function frame() {
        simulation.tick();
        simulation.clampToBounds();
        draw();
        if (!simulation.settled) {
          frameRef.current = requestAnimationFrame(frame);
        }
      }

      const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      if (reduceMotion || typeof requestAnimationFrame !== "function") {
        simulation.run();
        simulation.clampToBounds();
        draw();
      } else {
        draw();
        frameRef.current = requestAnimationFrame(frame);
      }
    }

    renderGraph();
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(renderGraph);
      resizeObserver.observe(parent);
    }

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      cancelFrame();
      redrawRef.current = null;
    };
  }, [edges, height, nodes]);

  function updateViewport(viewport: GraphViewport) {
    viewportRef.current = viewport;
    setZoomPercent(Math.round(viewport.scale * 100));
    redrawRef.current?.();
  }

  function zoomAt(requestedScale: number, anchor: Point) {
    updateViewport(zoomViewport(viewportRef.current, requestedScale, anchor));
  }

  function canvasCentre(): Point {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x:
        (canvas.clientWidth || rect.width || Number.parseFloat(canvas.style.width) || 1) /
        2,
      y:
        (canvas.clientHeight || rect.height || Number.parseFloat(canvas.style.height) || 1) /
        2,
    };
  }

  function zoomBy(factor: number) {
    zoomAt(viewportRef.current.scale * factor, canvasCentre());
  }

  function resetView() {
    updateViewport({ ...DEFAULT_VIEWPORT });
  }

  function zoomWithWheel(event: WheelEvent<HTMLCanvasElement>) {
    event.preventDefault();
    const anchor = canvasPoint(event.currentTarget, event.clientX, event.clientY);
    const factor = Math.exp(-event.deltaY * 0.0015);
    zoomAt(viewportRef.current.scale * factor, anchor);
  }

  function startPan(event: PointerEvent<HTMLCanvasElement>) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    panRef.current = {
      pointerId: event.pointerId,
      start: canvasPoint(event.currentTarget, event.clientX, event.clientY),
      offsetX: viewportRef.current.offsetX,
      offsetY: viewportRef.current.offsetY,
    };
    didDragRef.current = false;
  }

  function continuePan(event: PointerEvent<HTMLCanvasElement>) {
    const pan = panRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    const point = canvasPoint(event.currentTarget, event.clientX, event.clientY);
    const deltaX = point.x - pan.start.x;
    const deltaY = point.y - pan.start.y;
    if (Math.hypot(deltaX, deltaY) >= DRAG_THRESHOLD) {
      didDragRef.current = true;
    }
    viewportRef.current = {
      ...viewportRef.current,
      offsetX: pan.offsetX + deltaX,
      offsetY: pan.offsetY + deltaY,
    };
    redrawRef.current?.();
  }

  function finishPan(event: PointerEvent<HTMLCanvasElement>) {
    if (panRef.current?.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    panRef.current = null;
  }

  function selectAt(event: MouseEvent<HTMLCanvasElement>) {
    if (didDragRef.current) {
      didDragRef.current = false;
      return;
    }
    const canvas = event.currentTarget;
    const point = graphPointFromCanvas(
      canvasPoint(canvas, event.clientX, event.clientY),
      viewportRef.current,
    );
    selectionHandlerRef.current?.(hitTestGraph(
      point.x,
      point.y,
      hitNodesRef.current,
      hitEdgesRef.current,
    ));
  }

  return (
    <>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={`Knowledge graph: ${nodes.length} nodes, ${edges.length} connections`}
        aria-describedby="graph-interaction-help"
        className="absolute inset-0 block size-full touch-none cursor-grab active:cursor-grabbing"
        onClick={selectAt}
        onPointerDown={startPan}
        onPointerMove={continuePan}
        onPointerUp={finishPan}
        onPointerCancel={finishPan}
        onWheel={zoomWithWheel}
        onKeyDown={(event) => {
          if (event.key === "Escape") selectionHandlerRef.current?.(null);
          if (event.key === "+" || event.key === "=") {
            event.preventDefault();
            zoomBy(ZOOM_STEP);
          }
          if (event.key === "-") {
            event.preventDefault();
            zoomBy(1 / ZOOM_STEP);
          }
          if (event.key === "0") {
            event.preventDefault();
            resetView();
          }
        }}
        tabIndex={0}
      />
      <div
        role="group"
        aria-label="Graph view controls"
        className="absolute bottom-4 left-4 z-10 flex items-center gap-1 rounded-xl border border-[var(--cortex-graph-divider)] bg-background/85 p-1 shadow-lg backdrop-blur-sm"
      >
        <button
          type="button"
          aria-label="Zoom out"
          title="Zoom out"
          onClick={() => zoomBy(1 / ZOOM_STEP)}
          className="grid size-9 place-items-center rounded-lg text-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          −
        </button>
        <span
          aria-label={`Zoom level ${zoomPercent}%`}
          className="min-w-12 px-1 text-center font-mono text-[0.6875rem] text-subtle"
        >
          {zoomPercent}%
        </span>
        <button
          type="button"
          aria-label="Zoom in"
          title="Zoom in"
          onClick={() => zoomBy(ZOOM_STEP)}
          className="grid size-9 place-items-center rounded-lg text-lg text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          +
        </button>
        <span aria-hidden="true" className="mx-1 h-5 w-px bg-[var(--cortex-graph-divider)]" />
        <button
          type="button"
          onClick={resetView}
          className="min-h-9 rounded-lg px-3 text-xs font-medium text-muted transition-colors hover:bg-surface hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Reset view
        </button>
      </div>
    </>
  );
}
