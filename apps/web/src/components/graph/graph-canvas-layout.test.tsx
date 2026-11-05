import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GraphCanvas } from "@/components/graph/graph-canvas";
import type { GraphNode } from "@/lib/api-types";

/**
 * P-14.1: opening the inspector must not move the graph.
 *
 * The inspector is a sibling of the canvas in a flex row, so selecting a node
 * takes 22rem off the canvas and fires the ResizeObserver. The canvas used to
 * rebuild its whole simulation on that event, which re-seeded every node -- so
 * clicking one node rearranged the graph, including the node just clicked.
 *
 * These tests drive the observer directly rather than mounting the real
 * inspector: the bug is about what the canvas does when its element changes
 * size, whatever caused that.
 */

const WIDE = 960;
const NARROW = 608; // 960 minus a 22rem inspector
const HEIGHT = 560;

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

/** The element size every `getBoundingClientRect` reports, so a test can shrink it. */
const size = { width: WIDE, height: HEIGHT };

let resize: (() => void) | null = null;

function stubResizeObserver() {
  resize = null;
  class FakeResizeObserver {
    constructor(callback: () => void) {
      resize = callback;
    }
    observe() {}
    disconnect() {
      resize = null;
    }
  }
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
}

function node(key: string, type: GraphNode["type"], title: string): GraphNode {
  return { key, id: 1, type, title, url: null, state: null, repo: null, number: null };
}

const NODES: GraphNode[] = [
  node("Author:1", "Author", "alice"),
  node("Author:2", "Author", "bob"),
  node("PullRequest:100", "PullRequest", "#1 Add thing"),
  node("Issue:200", "Issue", "#2 Bug"),
];

const EDGES = [
  { source: "Author:1", target: "PullRequest:100", type: "AUTHORED" },
  { source: "Author:2", target: "Issue:200", type: "AUTHORED" },
];

/** Where the circles were drawn: one entry per `arc` call, rounded. */
function circleCentres(ctx: Ctx2D) {
  return ctx.arc.mock.calls.map(([x, y]) => [Math.round(Number(x)), Math.round(Number(y))]);
}

/** Where the squares were drawn, from `rect(x, y, w, h)`. */
function squareCorners(ctx: Ctx2D) {
  return ctx.rect.mock.calls.map(([x, y]) => [Math.round(Number(x)), Math.round(Number(y))]);
}

function lastPan(ctx: Ctx2D) {
  const [x, y] = (ctx.translate.mock.calls.at(-1) ?? []) as number[];
  return { x, y };
}

beforeEach(() => {
  size.width = WIDE;
  size.height = HEIGHT;
  vi.stubGlobal("requestAnimationFrame", vi.fn().mockReturnValue(1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  stubResizeObserver();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    () =>
      ({
        width: size.width,
        height: size.height,
        top: 0,
        left: 0,
        right: size.width,
        bottom: size.height,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mountCanvas() {
  const ctx = stubCanvas();
  render(<GraphCanvas nodes={NODES} edges={EDGES} />);
  return { ctx, canvas: screen.getByRole("img") as HTMLCanvasElement };
}

/** Shrink the canvas the way opening the inspector does. */
function openInspector() {
  size.width = NARROW;
  resize?.();
}

describe("resizing the canvas", () => {
  it("leaves every node exactly where it was", () => {
    const { ctx } = mountCanvas();
    const circlesBefore = circleCentres(ctx);
    const squaresBefore = squareCorners(ctx);
    expect(circlesBefore.length).toBeGreaterThan(0);
    ctx.arc.mockClear();
    ctx.rect.mockClear();

    openInspector();

    expect(circleCentres(ctx)).toEqual(circlesBefore);
    expect(squareCorners(ctx)).toEqual(squaresBefore);
  });

  it("repaints rather than leaving the old frame on screen", () => {
    const { ctx } = mountCanvas();
    ctx.clearRect.mockClear();

    openInspector();

    expect(ctx.clearRect).toHaveBeenCalled();
    // Cleared at the new width, not the old one, or the surplus smears.
    expect(ctx.clearRect).toHaveBeenLastCalledWith(0, 0, NARROW, HEIGHT);
  });

  it("slides the view by half the change, so the middle stays the middle", () => {
    const { ctx } = mountCanvas();
    const before = lastPan(ctx);

    openInspector();

    expect(lastPan(ctx).x).toBeCloseTo(before.x + (NARROW - WIDE) / 2, 5);
    expect(lastPan(ctx).y).toBeCloseTo(before.y, 5);
  });

  it("resizes the canvas element itself", () => {
    const { ctx, canvas } = mountCanvas();
    expect(canvas.style.width).toBe(`${WIDE}px`);

    openInspector();

    expect(canvas.style.width).toBe(`${NARROW}px`);
    expect(ctx.setTransform).toHaveBeenCalled();
  });

  it("keeps the layout when the canvas grows again", () => {
    const { ctx } = mountCanvas();
    const circlesBefore = circleCentres(ctx);

    openInspector();
    ctx.arc.mockClear();
    size.width = WIDE;
    resize?.();

    expect(circleCentres(ctx)).toEqual(circlesBefore);
  });

  it("does nothing once unmounted", () => {
    const ctx = stubCanvas();
    const { unmount } = render(<GraphCanvas nodes={NODES} edges={EDGES} />);
    unmount();
    ctx.clearRect.mockClear();

    size.width = NARROW;
    resize?.();

    expect(ctx.clearRect).not.toHaveBeenCalled();
  });
});

describe("the layout itself", () => {
  it("is the same for the same graph, so a reload does not reshuffle it", () => {
    const first = mountCanvas();
    const before = circleCentres(first.ctx);

    cleanup();
    const second = mountCanvas();

    expect(circleCentres(second.ctx)).toEqual(before);
  });
});
