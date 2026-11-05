import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SourceInventory } from "@/components/sources/source-inventory";
import { WorkspaceProvider } from "@/components/workspaces/workspace-context";
import type { WorkspaceRole, WorkspaceSource } from "@/lib/api-types";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

/** Relative to the clock, so "5 min ago" does not depend on a fixed date. */
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
    channels: 0,
    messages: 0,
    display_name: null,
    last_attempted_at: minutesAgo(5),
    last_synced_at: minutesAgo(5),
    last_error: null,
    last_synced_by: "11111111-0000-4000-8000-000000000001",
    last_synced_by_name: "Ashwath",
    ...over,
  };
}

function renderInventory(role: WorkspaceRole = "OWNER") {
  return render(
    <WorkspaceProvider
      value={{
        workspaceId: WORKSPACE_ID,
        workspace: {
          id: WORKSPACE_ID,
          name: "Cortex",
          description: null,
          role,
          // The UI reads permissions, not the role name (US-21 custom roles).
          permissions: role === "VIEWER" ? [] : ["sources.write"],
          created_at: "2026-09-24T00:00:00Z",
        },
        user: null,
        isLoading: false,
        error: null,
      }}
    >
      <SourceInventory workspaceId={WORKSPACE_ID} />
    </WorkspaceProvider>,
  );
}

const { replace, routerMock } = vi.hoisted(() => {
  const replaceFn = vi.fn();
  return {
    replace: replaceFn,
    routerMock: { replace: replaceFn, push: vi.fn(), refresh: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const INGESTED = { repo: "openai/cortex", pull_requests: 8, issues: 3 };

/**
 * Routes the endpoints the page uses: successive GETs of the source list walk
 * `pages` (the last one repeats, so polling settles), the re-sync POST goes to
 * `onIngest`, and the chat-connections read answers empty -- `ChatConnections`
 * has its own tests.
 */
function mockApi(
  pages: WorkspaceSource[][],
  onIngest: () => Promise<Response> = () => Promise.resolve(jsonResponse(INGESTED)),
) {
  let reads = 0;
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") return onIngest();
    if (String(input).endsWith("/connections")) {
      return Promise.resolve(jsonResponse([]));
    }
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

/** Advance fake timers inside act, so React flushes what the poll loaded. */
async function tick(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => replace.mockClear());
afterEach(() => vi.unstubAllGlobals());

describe("SourceInventory", () => {
  it("loads only the active workspace's source inventory", async () => {
    const fetchFn = mockFetch(200, []);
    renderInventory();
    await screen.findByText(/connect your first source/i);
    expect(fetchFn.mock.calls[0][0]).toBe(`/api/workspaces/${WORKSPACE_ID}/sources`);
  });

  it("shows connected repositories and their indexed counts", async () => {
    mockFetch(200, [source()]);
    renderInventory();
    const repository = await screen.findByRole("link", { name: /openai\/cortex/i });
    expect(repository).toHaveAttribute("href", "https://github.com/openai/cortex");
    expect(screen.getByText("1 source · 11 items indexed")).toBeInTheDocument();
  });

  // US-10 acceptance criteria.
  it("marks a successfully indexed source as connected, with when and who", async () => {
    mockFetch(200, [source()]);
    renderInventory();

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Synced 5 min ago by Ashwath")).toBeInTheDocument();
  });

  it("flags a source whose ingestion failed", async () => {
    mockFetch(200, [
      source({
        status: "FAILED",
        total_items: 0,
        pull_requests: 0,
        issues: 0,
        last_synced_at: null,
        last_synced_by: null,
        last_synced_by_name: null,
        last_error: "Repository openai/cortex not found or not accessible",
      }),
    ]);
    renderInventory();

    expect(await screen.findByText("Needs attention")).toBeInTheDocument();
    expect(
      screen.getByText("Repository openai/cortex not found or not accessible"),
    ).toBeInTheDocument();
    expect(screen.getByText("Never synced")).toBeInTheDocument();
    // A failed ingestion writes nothing, so the source is listed with no items.
    expect(screen.getByText("1 source · 0 items indexed")).toBeInTheDocument();
  });

  it("flags a failing source that is still showing older data", async () => {
    mockFetch(200, [
      source({
        status: "FAILED",
        last_synced_at: minutesAgo(3 * 24 * 60),
        last_error: "GitHub rate limit reached",
      }),
    ]);
    renderInventory();

    expect(await screen.findByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("Synced 3 days ago by Ashwath")).toBeInTheDocument();
  });

  it("shows an in-progress source as syncing", async () => {
    mockFetch(200, [
      source({ status: "PENDING", last_synced_at: null, last_synced_by_name: null }),
    ]);
    renderInventory();

    expect(await screen.findByText("Syncing…")).toBeInTheDocument();
  });

  it("lists a repo ingested before sync state was recorded, without a timestamp", async () => {
    mockFetch(200, [
      source({
        last_attempted_at: null,
        last_synced_at: null,
        last_synced_by: null,
        last_synced_by_name: null,
      }),
    ]);
    renderInventory();

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.queryByText(/synced/i)).not.toBeInTheDocument();
  });

  it("offers repository ingestion in an empty workspace", async () => {
    mockFetch(200, []);
    renderInventory();
    expect(await screen.findByRole("link", { name: /add github repository/i })).toHaveAttribute("href", `/workspaces/${WORKSPACE_ID}/ingest`);
  });

  it("keeps repository actions read-only for viewers", async () => {
    mockFetch(200, []);
    renderInventory("VIEWER");

    expect(await screen.findByText(/no indexed sources yet/i)).toBeInTheDocument();
    expect(screen.getByText(/ask a workspace owner or editor/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /add repository/i })).not.toBeInTheDocument();
  });

  it("shows access errors and can retry", async () => {
    // Routed by URL, not by call order: the page also reads /connections, and
    // a once-per-call mock would hand it the retry's response.
    let sourceReads = 0;
    const fetchFn = vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith("/connections")) {
        return Promise.resolve(jsonResponse([]));
      }
      sourceReads += 1;
      return Promise.resolve(
        sourceReads === 1
          ? jsonResponse({ detail: "Workspace access denied" }, 403)
          : jsonResponse([]),
      );
    });
    vi.stubGlobal("fetch", fetchFn);
    const user = userEvent.setup();
    renderInventory();
    expect(await screen.findByRole("alert")).toHaveTextContent(/access denied/i);
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText(/connect your first source/i)).toBeInTheDocument();
    expect(sourceReads).toBe(2);
  });

  it("renders a Slack source by its team name with chat counts", async () => {
    mockApi([
      [
        source({
          kind: "slack",
          repo: "T0ACME",
          display_name: "Acme",
          pull_requests: 0,
          issues: 0,
          channels: 2,
          messages: 30,
          total_items: 32,
        }),
      ],
    ]);
    renderInventory();

    // The team id is the data_sources key, not something a reader recognises.
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.queryByText("T0ACME")).not.toBeInTheDocument();
    expect(screen.getByText("Channels")).toBeInTheDocument();
    expect(screen.getByText("Messages")).toBeInTheDocument();
    expect(screen.queryByText("Pull requests")).not.toBeInTheDocument();
    // Slack has no addressable team URL, so the title is not a link.
    expect(screen.queryByRole("link", { name: /Acme/ })).not.toBeInTheDocument();
  });

  it("offers Re-sync only for repositories", async () => {
    // A chat re-sync needs channels chosen again, so the row cannot do it.
    mockApi([
      [
        source({ kind: "slack", repo: "T0ACME", display_name: "Acme" }),
        source(),
      ],
    ]);
    renderInventory();

    expect(
      await screen.findByRole("button", { name: /re-sync openai\/cortex/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /re-sync acme/i }),
    ).not.toBeInTheDocument();
  });

  // Re-syncing a connected source, and polling while one is mid-ingestion.
  it("re-syncs a connected repository without re-entering its URL", async () => {
    const fetchFn = mockApi([[source()]]);
    renderInventory();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync openai\/cortex/i }));

    await waitFor(() =>
      expect(fetchFn).toHaveBeenCalledWith(
        "/api/ingest/github",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const post = fetchFn.mock.calls.find(
      ([url]) => String(url) === "/api/ingest/github",
    );
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      repo_url: "https://github.com/openai/cortex",
      workspace_id: WORKSPACE_ID,
    });
  });

  it("shows the row as syncing until the re-sync finishes, then refreshes it", async () => {
    let finish: (() => void) | undefined;
    const inFlight = new Promise<Response>((resolve) => {
      finish = () => resolve(jsonResponse(INGESTED));
    });
    const fetchFn = mockApi(
      [[source()], [source({ last_synced_at: minutesAgo(0) })]],
      () => inFlight,
    );
    renderInventory();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync/i }));

    expect(await screen.findByText("Syncing…")).toBeInTheDocument();
    // One ingestion at a time: it shares the workspace's GitHub rate limit.
    expect(screen.getByRole("button", { name: /re-sync/i })).toBeDisabled();

    finish?.();

    expect(await screen.findByText("Synced just now by Ashwath")).toBeInTheDocument();
    expect(sourceReads(fetchFn)).toHaveLength(2);
    expect(screen.getByRole("button", { name: /re-sync/i })).toBeEnabled();
  });

  it("surfaces a re-sync that never reached the server", async () => {
    mockApi([[source()]], () => Promise.reject(new TypeError("Failed to fetch")));
    renderInventory();

    fireEvent.click(await screen.findByRole("button", { name: /re-sync/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not re-sync openai\/cortex/i,
    );
  });

  it("offers no re-sync to viewers", async () => {
    mockApi([[source()]]);
    renderInventory("VIEWER");

    await screen.findByRole("link", { name: /openai\/cortex/i });
    expect(screen.queryByRole("button", { name: /re-sync/i })).not.toBeInTheDocument();
  });

  it("polls while a source is mid-ingestion and stops once it settles", async () => {
    vi.useFakeTimers();
    try {
      const fetchFn = mockApi([
        [source({ status: "PENDING", last_synced_at: null })],
        [source()],
      ]);
      renderInventory();
      await tick();

      expect(screen.getByText("Syncing…")).toBeInTheDocument();
      expect(sourceReads(fetchFn)).toHaveLength(1);

      await tick(5_000);

      expect(sourceReads(fetchFn)).toHaveLength(2);
      expect(screen.getByText("Connected")).toBeInTheDocument();

      // Nothing is pending any more, so the interval is torn down.
      await tick(60_000);
      expect(sourceReads(fetchFn)).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not poll a settled source list", async () => {
    vi.useFakeTimers();
    try {
      const fetchFn = mockApi([[source()]]);
      renderInventory();
      await tick();
      await tick(60_000);

      expect(sourceReads(fetchFn)).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("redirects unauthenticated users to login", async () => {
    mockFetch(401, { detail: "Not authenticated" });
    renderInventory();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});
