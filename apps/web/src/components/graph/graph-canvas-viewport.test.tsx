import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GraphCanvas } from "@/components/graph/graph-canvas";
import type { GraphNode } from "@/lib/api-types";

/**
 * The gestures #18 left open: the wheel must cancel the page scroll, panning
 * must stop at the edge of the scene, and the zoom range has to be usable.
 *
 * The canvas falls back to this size when jsdom reports a zero-sized parent,
 * and `canvasSize()` reads it back off the inline style.
 */
const SCENE_WIDTH = 960;
const SCENE_HEIGHT = 560;

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
  node("PullRequest:100", "PullRequest", "#1 Add thing"),
];

function mountCanvas() {
  const onSelectionChange = vi.fn();
  render(<GraphCanvas nodes={NODES} edges={[]} onSelectionChange={onSelectionChange} />);
  return { canvas: screen.getByRole("img") as HTMLCanvasElement, onSelectionChange };
}

/** The offset the last paint applied, from ctx.translate(offsetX, offsetY). */
function lastPan(ctx: Ctx2D) {
  const [x, y] = (ctx.translate.mock.calls.at(-1) ?? []) as number[];
  return { x, y };
}

function zoomPercent() {
  return screen.getByLabelText(/^Zoom level/).textContent;
}

beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", vi.fn().mockReturnValue(1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("wheel zoom", () => {
  it("registers the wheel listener non-passively", () => {
    // React registers onWheel passively at the root, where preventDefault() is
    // ignored and the page scrolls behind the zoom. Only a native listener with
    // passive: false can stop it.
    const addEventListener = vi.spyOn(HTMLCanvasElement.prototype, "addEventListener");
    stubCanvas();
    mountCanvas();

    const wheel = addEventListener.mock.calls.find(([type]) => type === "wheel");
    expect(wheel).toBeDefined();
    expect(wheel?.[2]).toEqual({ passive: false });
  });

  it("cancels the page scroll it replaces", () => {
    stubCanvas();
    const { canvas } = mountCanvas();

    // fireEvent returns false when a listener called preventDefault.
    expect(fireEvent.wheel(canvas, { deltaY: -120, clientX: 480, clientY: 280 })).toBe(false);
  });

  it("grows and shrinks the drawn graph", () => {
    stubCanvas();
    const { canvas } = mountCanvas();

    fireEvent.wheel(canvas, { deltaY: -240, clientX: 480, clientY: 280 });
    expect(Number.parseInt(zoomPercent() ?? "0", 10)).toBeGreaterThan(100);

    fireEvent.wheel(canvas, { deltaY: 480, clientX: 480, clientY: 280 });
    expect(Number.parseInt(zoomPercent() ?? "0", 10)).toBeLessThan(100);
  });
});

describe("zoom range", () => {
  it("reaches 4x in and 0.25x out", () => {
    stubCanvas();
    mountCanvas();

    const zoomIn = screen.getByRole("button", { name: "Zoom in" });
    for (let i = 0; i < 20; i += 1) fireEvent.click(zoomIn);
    expect(zoomPercent()).toBe("400%");

    const zoomOut = screen.getByRole("button", { name: "Zoom out" });
    for (let i = 0; i < 40; i += 1) fireEvent.click(zoomOut);
    expect(zoomPercent()).toBe("25%");

    fireEvent.click(screen.getByRole("button", { name: "Reset view" }));
    expect(zoomPercent()).toBe("100%");
  });
});

describe("pan clamping", () => {
  function drag(canvas: HTMLCanvasElement, toX: number, toY: number) {
    fireEvent.pointerDown(canvas, { pointerId: 1, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: toX, clientY: toY });
    fireEvent.pointerUp(canvas, { pointerId: 1, clientX: toX, clientY: toY });
  }

  it("follows a modest drag exactly", () => {
    const ctx = stubCanvas();
    const { canvas } = mountCanvas();

    drag(canvas, 240, 160);

    expect(lastPan(ctx)).toEqual({ x: 140, y: 60 });
  });

  it("stops before the graph leaves the screen", () => {
    const ctx = stubCanvas();
    const { canvas } = mountCanvas();

    drag(canvas, 100_000, 100_000);

    const panned = lastPan(ctx);
    expect(panned.x).toBeLessThan(SCENE_WIDTH);
    expect(panned.y).toBeLessThan(SCENE_HEIGHT);
  });

  it("stops in the other direction too", () => {
    const ctx = stubCanvas();
    const { canvas } = mountCanvas();

    drag(canvas, -100_000, -100_000);

    const panned = lastPan(ctx);
    expect(panned.x + SCENE_WIDTH).toBeGreaterThan(0);
    expect(panned.y + SCENE_HEIGHT).toBeGreaterThan(0);
  });

  it("does not select what was under a drag", () => {
    stubCanvas();
    const { canvas, onSelectionChange } = mountCanvas();

    drag(canvas, 240, 160);
    fireEvent.click(canvas, { clientX: 240, clientY: 160 });

    expect(onSelectionChange).not.toHaveBeenCalled();
  });
});
