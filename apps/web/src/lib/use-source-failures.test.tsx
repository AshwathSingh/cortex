import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSourceFailures } from "@/lib/use-source-failures";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function failure(repo: string) {
  return {
    repo,
    kind: "github",
    category: "AUTH" as const,
    label: "Authorization expired",
    message: null,
    advice: "Sign in again.",
    needs_reauth: true,
    can_retry: false,
    last_attempted_at: null,
    last_synced_at: null,
    last_synced_by_name: null,
  };
}

/** A probe that renders what the hook reports, plus a button to refresh it. */
function Probe() {
  const { failures, isLoading, refresh } = useSourceFailures(WORKSPACE_ID);
  return (
    <div>
      <p data-testid="state">{isLoading ? "loading" : "loaded"}</p>
      <ul>
        {failures.map((entry) => (
          <li key={entry.repo}>{entry.repo}</li>
        ))}
      </ul>
      <button type="button" onClick={refresh}>
        refresh
      </button>
    </div>
  );
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function tick(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("useSourceFailures", () => {
  it("reads the workspace's failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse([failure("openai/cortex")]))),
    );

    render(<Probe />);
    await tick();

    expect(screen.getByText("openai/cortex")).toBeInTheDocument();
    expect(screen.getByTestId("state")).toHaveTextContent("loaded");
  });

  it("asks only its own workspace", async () => {
    const fetchFn = vi.fn((input: RequestInfo | URL) => {
      void input;
      return Promise.resolve(jsonResponse([]));
    });
    vi.stubGlobal("fetch", fetchFn);

    render(<Probe />);
    await tick();

    expect(fetchFn.mock.calls.map(([url]) => String(url))).toEqual([
      `/api/workspaces/${WORKSPACE_ID}/source-failures`,
    ]);
  });

  it("notices a failure that appears while the reader is elsewhere", async () => {
    /** AC1 is about being told without going to look, and a source can break
     *  on somebody else's re-sync. */
    let reads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        reads += 1;
        return Promise.resolve(
          jsonResponse(reads === 1 ? [] : [failure("openai/cortex")]),
        );
      }),
    );

    render(<Probe />);
    await tick();
    expect(screen.queryByText("openai/cortex")).not.toBeInTheDocument();

    await tick(30_000);

    expect(screen.getByText("openai/cortex")).toBeInTheDocument();
  });

  it("clears the notice once the source syncs (AC3)", async () => {
    let reads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        reads += 1;
        return Promise.resolve(
          jsonResponse(reads === 1 ? [failure("openai/cortex")] : []),
        );
      }),
    );

    render(<Probe />);
    await tick();
    expect(screen.getByText("openai/cortex")).toBeInTheDocument();

    await tick(30_000);

    expect(screen.queryByText("openai/cortex")).not.toBeInTheDocument();
  });

  it("re-reads on demand, so a retry updates without waiting for the poll", async () => {
    const fetchFn = vi.fn(() => Promise.resolve(jsonResponse([])));
    vi.stubGlobal("fetch", fetchFn);

    render(<Probe />);
    await tick();
    const before = fetchFn.mock.calls.length;

    await act(async () => {
      screen.getByRole("button", { name: "refresh" }).click();
    });
    await tick();

    expect(fetchFn.mock.calls.length).toBeGreaterThan(before);
  });

  it("stays quiet when the check itself fails", async () => {
    /** This runs on every workspace page. "Could not check for broken sources"
     *  on all of them, for the length of a hiccup, is noise. */
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    render(<Probe />);
    await tick();

    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    // Not stuck on "loading" either: a silent failure still has to finish.
    expect(screen.getByTestId("state")).toHaveTextContent("loaded");
  });

  it("reports nothing for a workspace the caller cannot see", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ detail: "no access" }, 403))),
    );

    render(<Probe />);
    await tick();

    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("stops polling once unmounted", async () => {
    const fetchFn = vi.fn(() => Promise.resolve(jsonResponse([])));
    vi.stubGlobal("fetch", fetchFn);

    const { unmount } = render(<Probe />);
    await tick();
    unmount();
    const afterUnmount = fetchFn.mock.calls.length;

    await tick(90_000);

    expect(fetchFn.mock.calls.length).toBe(afterUnmount);
  });
});
