import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ACTIVITY_POLL_MS, useConnectionActivity } from "@/lib/use-connection-activity";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

function summaryResponse(analysis: Record<string, number>) {
  return new Response(
    JSON.stringify({ enabled: true, pending_review: 0, analysis }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function mockFetch(pages: Record<string, number>[]) {
  let reads = 0;
  const fn = vi.fn(() => {
    const page = pages[Math.min(reads, pages.length - 1)];
    reads += 1;
    return Promise.resolve(summaryResponse(page));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

async function tick(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useConnectionActivity", () => {
  it("keeps polling through the grace window even if the agent has not started yet", async () => {
    // The ingestion event just queued a background job (events.emit_artifact_ingested);
    // nothing is "running" or "pending" the moment the frontend first asks, but the
    // job starts moments later and must still be picked up without a page reload.
    vi.useFakeTimers();
    const fetchFn = mockFetch([
      { done: 5 }, // nothing in flight yet (the race window)
      { done: 5 }, // still nothing
      { running: 1, done: 5 }, // the agent has now started
    ]);
    const { result, rerender } = renderHook(
      ({ reloadToken }) => useConnectionActivity(WORKSPACE_ID, reloadToken),
      { initialProps: { reloadToken: 1 } },
    );
    await tick();
    expect(fetchFn).toHaveBeenCalledTimes(1);

    await tick(ACTIVITY_POLL_MS);
    expect(fetchFn).toHaveBeenCalledTimes(2);

    await tick(ACTIVITY_POLL_MS);
    expect(fetchFn).toHaveBeenCalledTimes(3);
    expect(result.current.summary?.analysis).toEqual({ running: 1, done: 5 });

    rerender({ reloadToken: 1 });
  });

  it("stops polling once the grace window has passed and nothing is in flight", async () => {
    vi.useFakeTimers();
    const fetchFn = mockFetch([{ done: 5 }]);
    renderHook(({ reloadToken }) => useConnectionActivity(WORKSPACE_ID, reloadToken), {
      initialProps: { reloadToken: 1 },
    });
    await tick();

    // Burn through the grace window: every read keeps reporting nothing in flight.
    await tick(ACTIVITY_POLL_MS * 10);
    const settled = fetchFn.mock.calls.length;

    await tick(ACTIVITY_POLL_MS * 10);
    expect(fetchFn.mock.calls.length).toBe(settled);
  });

  it("keeps polling indefinitely while the agent is actively running", async () => {
    vi.useFakeTimers();
    const fetchFn = mockFetch([{ running: 1, done: 5 }]);
    renderHook(({ reloadToken }) => useConnectionActivity(WORKSPACE_ID, reloadToken), {
      initialProps: { reloadToken: 1 },
    });
    await tick();
    const afterFirst = fetchFn.mock.calls.length;

    await tick(ACTIVITY_POLL_MS * 10);
    expect(fetchFn.mock.calls.length).toBeGreaterThan(afterFirst + 5);
  });
});
