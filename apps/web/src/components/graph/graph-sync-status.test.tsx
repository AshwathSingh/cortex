import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GraphSyncStatus, MAX_SYNC_POLLS } from "@/components/graph/graph-sync-status";
import { WorkspaceProvider } from "@/components/workspaces/workspace-context";
import type { WorkspaceRole, WorkspaceSource } from "@/lib/api-types";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

const { replace, routerMock } = vi.hoisted(() => {
  const replaceFn = vi.fn();
  return {
    replace: replaceFn,
    routerMock: { replace: replaceFn, push: vi.fn(), refresh: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function source(over: Partial<WorkspaceSource> = {}): WorkspaceSource {
  return {
    repo: "openai/cortex",
    kind: "github",
    status: "SUCCESS",
    pull_requests: 8,
    issues: 3,
    total_items: 11,
    last_attempted_at: minutesAgo(5),
    last_synced_at: minutesAgo(5),
    last_error: null,
    last_synced_by: "11111111-0000-4000-8000-000000000001",
    last_synced_by_name: "Ashwath",
    ...over,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockApi(
  pages: WorkspaceSource[][],
  onIngest: () => Promise<Response> = () =>
    Promise.resolve(jsonResponse({ repo: "openai/cortex", pull_requests: 8, issues: 3 })),
) {
  let reads = 0;
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") return onIngest();
    const page = pages[Math.min(reads, pages.length - 1)];
    reads += 1;
    return Promise.resolve(jsonResponse(page));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function sourceReads(fetchFn: ReturnType<typeof mockApi>) {
  return fetchFn.mock.calls.filter(([url]) => String(url).endsWith("/sources"));
}

function renderStatus(role: WorkspaceRole = "OWNER") {
  return render(
    <WorkspaceProvider
      value={{
        workspaceId: WORKSPACE_ID,
        workspace: {
          id: WORKSPACE_ID,
          name: "Cortex",
          description: null,
          role,
          created_at: "2026-09-24T00:00:00Z",
        },
        user: null,
        isLoading: false,
        error: null,
      }}
    >
      <GraphSyncStatus workspaceId={WORKSPACE_ID} />
    </WorkspaceProvider>,
  );
}

async function tick(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => replace.mockClear());
afterEach(() => vi.unstubAllGlobals());

describe("GraphSyncStatus", () => {
  it("says how old the graph on screen is", async () => {
    mockApi([[source()]]);
    renderStatus();

    expect(await screen.findByText("Synced 5 min ago")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("reports the newest success across several sources", async () => {
    mockApi([[
      source({ repo: "openai/old", last_synced_at: minutesAgo(3 * 24 * 60) }),
      source({ repo: "openai/new", last_synced_at: minutesAgo(2) }),
    ]]);
    renderStatus();

    expect(await screen.findByText("Synced 2 min ago")).toBeInTheDocument();
  });

  it("flags a failing source without hiding how stale the graph is", async () => {
    mockApi([[
      source({ repo: "openai/ok" }),
      source({
        repo: "openai/broken",
        status: "FAILED",
        last_synced_at: minutesAgo(3 * 24 * 60),
        last_error: "Repository openai/broken not found or not accessible",
      }),
    ]]);
    renderStatus();

    expect(await screen.findByText(/Needs attention · 1 of 2 sources/)).toBeInTheDocument();
    expect(screen.getByText("Synced 5 min ago")).toBeInTheDocument();
  });

  it("re-syncs every connected source", async () => {
    const fetchFn = mockApi([[source({ repo: "openai/one" }), source({ repo: "openai/two" })]]);
    renderStatus();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync all sources/i }));

    await waitFor(() => {
      const posts = fetchFn.mock.calls.filter(([, init]) => init?.method === "POST");
      expect(posts.map(([, init]) => JSON.parse(String(init?.body)).repo_url)).toEqual([
        "https://github.com/openai/one",
        "https://github.com/openai/two",
      ]);
    });
  });

  it("shows the refresh running and reloads when it finishes", async () => {
    let finish: (() => void) | undefined;
    const inFlight = new Promise<Response>((resolve) => {
      finish = () => resolve(jsonResponse({ repo: "openai/cortex", pull_requests: 8, issues: 3 }));
    });
    const fetchFn = mockApi(
      [[source()], [source({ last_synced_at: minutesAgo(0) })]],
      () => inFlight,
    );
    renderStatus();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync/i }));

    expect(await screen.findByText("Syncing…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /re-sync/i })).toBeDisabled();

    finish?.();

    expect(await screen.findByText("Synced just now")).toBeInTheDocument();
    expect(sourceReads(fetchFn)).toHaveLength(2);
  });

  it("surfaces a refresh that never reached the server", async () => {
    mockApi([[source()]], () => Promise.reject(new TypeError("Failed to fetch")));
    renderStatus();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not reach/i);
  });

  it("offers no refresh to viewers", async () => {
    mockApi([[source()]]);
    renderStatus("VIEWER");

    expect(await screen.findByText("Synced 5 min ago")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /re-sync/i })).not.toBeInTheDocument();
  });

  it("renders nothing for a workspace with no sources", async () => {
    const fetchFn = mockApi([[]]);
    renderStatus();

    await waitFor(() => expect(fetchFn).toHaveBeenCalled());
    expect(screen.queryByText(/synced/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /re-sync/i })).not.toBeInTheDocument();
  });

  it("stays out of the way when the sources read fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "nope" }, 503)));
    const { container } = renderStatus();

    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(replace).not.toHaveBeenCalled();
  });

  it("redirects unauthenticated callers to login", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Not authenticated" }, 401)));
    renderStatus();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  // Review fixes: the canvas must reload, a dead ingestion must not lock the
  // page, and one broken source must not strand the rest.
  it("tells the page to reload the canvas when a sync lands new data", async () => {
    const onGraphChanged = vi.fn();
    mockApi([[source()], [source({ last_synced_at: minutesAgo(0) })]]);
    render(
      <WorkspaceProvider
        value={{
          workspaceId: WORKSPACE_ID,
          workspace: {
            id: WORKSPACE_ID, name: "Cortex", description: null,
            role: "OWNER", created_at: "2026-09-24T00:00:00Z",
          },
          user: null, isLoading: false, error: null,
        }}
      >
        <GraphSyncStatus workspaceId={WORKSPACE_ID} onGraphChanged={onGraphChanged} />
      </WorkspaceProvider>,
    );

    expect(await screen.findByText("Synced 5 min ago")).toBeInTheDocument();
    // The first load is not a change; the graph is already on screen.
    expect(onGraphChanged).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /re-sync/i }));

    expect(await screen.findByText("Synced just now")).toBeInTheDocument();
    expect(onGraphChanged).toHaveBeenCalledTimes(1);
  });

  it("says how long an in-flight ingestion has been running", async () => {
    mockApi([[
      source({ status: "PENDING", last_synced_at: null, last_attempted_at: minutesAgo(2) }),
    ]]);
    renderStatus();

    // Reported, not inferred: whether it is still alive is the server's
    // question, and it answers it by holding or releasing the lease.
    expect(await screen.findByText("Syncing… started 2 min ago")).toBeInTheDocument();
  });

  it("leaves the retry reachable while the server reports an ingestion", async () => {
    // A row the server never cleared must not lock the page out of retrying.
    // Clicking asks the server, which refuses with 409 only if the lease is
    // genuinely still held.
    mockApi(
      [[source({ status: "PENDING", last_synced_at: null, last_attempted_at: minutesAgo(45) })]],
      () => Promise.resolve(jsonResponse({ detail: "An ingestion of openai/cortex is already running" }, 409)),
    );
    renderStatus();

    const button = await screen.findByRole("button", { name: /re-sync/i });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    expect(await screen.findByRole("alert")).toHaveTextContent(/already running/i);
  });

  it("stops polling an ingestion that never finishes", async () => {
    vi.useFakeTimers();
    try {
      const fetchFn = mockApi([[
        source({ status: "PENDING", last_synced_at: null, last_attempted_at: minutesAgo(2) }),
      ]]);
      renderStatus();
      await tick();
      expect(sourceReads(fetchFn)).toHaveLength(1);

      // Still polling well before the ceiling.
      await tick(5_000);
      expect(sourceReads(fetchFn).length).toBeGreaterThan(1);

      // 120 polls at 5s is ten minutes. Past that the timer is torn down rather
      // than left running for the life of the tab, so nothing more is read.
      await tick(5_000 * MAX_SYNC_POLLS);
      const settled = sourceReads(fetchFn).length;

      await tick(5_000 * 50);
      expect(sourceReads(fetchFn)).toHaveLength(settled);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops the run on a failure that is not one repository's fault", async () => {
    const fetchFn = mockApi(
      [[source({ repo: "openai/one" }), source({ repo: "openai/two" })]],
      () => Promise.resolve(jsonResponse({ detail: "GitHub rate limit reached" }, 429)),
    );
    renderStatus();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/rate limit/i);
    // Carrying on would re-spend a rate limit that is already exhausted.
    await waitFor(() =>
      expect(fetchFn.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1),
    );
  });

  it("stops the run when the graph database is down", async () => {
    const fetchFn = mockApi(
      [[source({ repo: "openai/one" }), source({ repo: "openai/two" })]],
      () => Promise.resolve(jsonResponse({ detail: "Graph database unavailable" }, 503)),
    );
    renderStatus();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/graph database/i);
    await waitFor(() =>
      expect(fetchFn.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1),
    );
  });

  it("re-syncs the sources after one that fails", async () => {
    let attempt = 0;
    const fetchFn = mockApi(
      [[source({ repo: "openai/one" }), source({ repo: "openai/bad" }), source({ repo: "openai/two" })]],
      () => {
        attempt += 1;
        return Promise.resolve(
          attempt === 2
            ? jsonResponse({ detail: "Repository openai/bad not found" }, 404)
            : jsonResponse({ repo: "openai/one", pull_requests: 8, issues: 3 }),
        );
      },
    );
    renderStatus();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync/i }));

    // All three are attempted; the failure does not strand the third.
    await waitFor(() => {
      const posts = fetchFn.mock.calls.filter(([, init]) => init?.method === "POST");
      expect(posts.map(([, init]) => JSON.parse(String(init?.body)).repo_url)).toEqual([
        "https://github.com/openai/one",
        "https://github.com/openai/bad",
        "https://github.com/openai/two",
      ]);
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not re-sync openai/bad.",
    );
  });

  it("stops the run when the server itself is unreachable", async () => {
    const fetchFn = mockApi(
      [[source({ repo: "openai/one" }), source({ repo: "openai/two" })]],
      () => Promise.reject(new TypeError("Failed to fetch")),
    );
    renderStatus();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not reach/i);
    // Carrying on would just fail identically for every remaining source.
    await waitFor(() =>
      expect(fetchFn.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1),
    );
  });

  it("polls while an ingestion is running and stops once it settles", async () => {
    vi.useFakeTimers();
    try {
      const fetchFn = mockApi([
        [source({ status: "PENDING", last_synced_at: null })],
        [source()],
      ]);
      renderStatus();
      await tick();

      expect(screen.getByText(/^Syncing…/)).toBeInTheDocument();
      expect(sourceReads(fetchFn)).toHaveLength(1);

      await tick(5_000);
      expect(sourceReads(fetchFn)).toHaveLength(2);
      expect(screen.getByText("Connected")).toBeInTheDocument();

      await tick(60_000);
      expect(sourceReads(fetchFn)).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
