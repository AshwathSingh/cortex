import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useWorkspaceFlags } from "@/lib/use-workspace-flags";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function Probe() {
  const { state, refresh, isChecking } = useWorkspaceFlags(WORKSPACE_ID);
  return (
    <div>
      <p data-testid="kind">{state.kind}</p>
      <p data-testid="checking">{String(isChecking)}</p>
      <p data-testid="status">
        {state.kind === "error" ? String(state.status) : ""}
      </p>
      <p data-testid="count">
        {state.kind === "ready" ? state.data.flags.length : ""}
      </p>
      <button type="button" onClick={refresh}>
        refresh
      </button>
    </div>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useWorkspaceFlags", () => {
  it("runs the check once on mount and never on a timer", async () => {
    /** Each read is a fresh pass over the whole workspace, so repeating it
     *  behind the reader's back would be a graph scan nobody asked for. */
    vi.useFakeTimers();
    const fetchFn = vi.fn(() =>
      Promise.resolve(jsonResponse({ workspace_id: WORKSPACE_ID, generated_at: "", flags: [], truncated: false })),
    );
    vi.stubGlobal("fetch", fetchFn);

    render(<Probe />);
    await vi.advanceTimersByTimeAsync(0);
    const afterMount = fetchFn.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10 * 60_000);

    expect(afterMount).toBe(1);
    expect(fetchFn.mock.calls.length).toBe(1);
    vi.useRealTimers();
  });

  it("reports the findings it got", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            workspace_id: WORKSPACE_ID,
            generated_at: new Date().toISOString(),
            flags: [{ id: "a" }, { id: "b" }],
            truncated: false,
          }),
        ),
      ),
    );

    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId("kind")).toHaveTextContent("ready"));
    expect(screen.getByTestId("count")).toHaveTextContent("2");
    expect(screen.getByTestId("checking")).toHaveTextContent("false");
  });

  it("carries the status so a caller can act on a 401 without reading the message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ detail: "Not authenticated" }, 401))),
    );

    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("401"));
  });

  it("has no status when the request never reached Cortex", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));

    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("null"));
    expect(screen.getByTestId("kind")).toHaveTextContent("error");
  });

  it("stops checking once unmounted", async () => {
    const fetchFn = vi.fn(() =>
      Promise.resolve(jsonResponse({ workspace_id: WORKSPACE_ID, generated_at: "", flags: [], truncated: false })),
    );
    vi.stubGlobal("fetch", fetchFn);

    const { unmount } = render(<Probe />);
    await waitFor(() => expect(fetchFn).toHaveBeenCalled());
    unmount();
    const calls = fetchFn.mock.calls.length;

    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(fetchFn.mock.calls.length).toBe(calls);
  });
});
