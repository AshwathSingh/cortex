import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewQueue } from "@/components/review/review-queue";
import type { WorkspaceFlag, WorkspaceFlags } from "@/lib/api-types";

/**
 * T-28.2: the review queue reading the Pruning Agent's real findings.
 *
 * This file replaces the placeholder suite that covered a hard-coded `items`
 * prop; that prop existed to hold the page's shape until there was something to
 * put in it, and US-28 is that something.
 */

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

const { replace, routerMock } = vi.hoisted(() => {
  const replaceFn = vi.fn();
  return {
    replace: replaceFn,
    routerMock: { replace: replaceFn, push: vi.fn(), refresh: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

function flag(over: Partial<WorkspaceFlag> = {}): WorkspaceFlag {
  return {
    id: "flag-1",
    rule: "STALE",
    label: "Out of date",
    severity: "MEDIUM",
    summary: "#12 Fix login redirect is still open but nothing has touched it for 7 months.",
    targets: [
      {
        key: "Issue:12",
        type: "Issue",
        title: "Fix login redirect",
        url: "https://github.com/cortex/app/issues/12",
      },
    ],
    evidence: [
      { label: "Last activity", detail: "2026-04-01, 7 months ago" },
      { label: "State", detail: "open" },
    ],
    ...over,
  };
}

function payload(flags: WorkspaceFlag[], over: Partial<WorkspaceFlags> = {}): WorkspaceFlags {
  return {
    workspace_id: WORKSPACE_ID,
    generated_at: new Date(Date.now() - 30_000).toISOString(),
    flags,
    truncated: false,
    ...over,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFlags(body: unknown, status = 200) {
  const fn = vi.fn((input: RequestInfo | URL) => {
    void input;
    return Promise.resolve(jsonResponse(body, status));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => replace.mockClear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ReviewQueue", () => {
  it("asks its own workspace for its findings", async () => {
    const fetchFn = mockFlags(payload([]));
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    await screen.findByText(/Nothing needs review/);

    expect(fetchFn.mock.calls.map(([url]) => String(url))).toEqual([
      `/api/workspaces/${WORKSPACE_ID}/flags`,
    ]);
  });

  it("says nothing needs review when nothing does", async () => {
    mockFlags(payload([]));
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByText(/Nothing needs review/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /review indexed sources/i }),
    ).toHaveAttribute("href", `/workspaces/${WORKSPACE_ID}/sources`);
  });

  it("shows a flag's summary and how serious it is (AC2)", async () => {
    mockFlags(payload([flag()]));
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByText(flag().summary)).toBeInTheDocument();
    expect(screen.getByText("Out of date")).toBeInTheDocument();
    expect(screen.getByText("Medium priority")).toBeInTheDocument();
    expect(screen.getByText(/1 signal needs review/)).toBeInTheDocument();
  });

  it("shows the evidence that produced it (AC4)", async () => {
    mockFlags(payload([flag()]));
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    await screen.findByText(flag().summary);

    expect(screen.getByText("Why this was flagged")).toBeInTheDocument();
    expect(screen.getByText("Last activity:")).toBeInTheDocument();
    expect(screen.getByText("2026-04-01, 7 months ago")).toBeInTheDocument();
  });

  it("links each flagged item to its source", async () => {
    mockFlags(payload([flag()]));
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    const link = await screen.findByRole("link", { name: /Fix login redirect/ });
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/cortex/app/issues/12",
    );
  });

  it("still names an item that has nowhere to link to", async () => {
    mockFlags(
      payload([
        flag({
          targets: [
            { key: "Issue:12", type: "Issue", title: "No link here", url: null },
          ],
        }),
      ]),
    );
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByText("No link here")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /No link here/ }),
    ).not.toBeInTheDocument();
  });

  it("names both items in a contradiction", async () => {
    mockFlags(
      payload([
        flag({
          rule: "CONTRADICTED",
          label: "Contradicted",
          severity: "HIGH",
          targets: [
            { key: "PullRequest:1", type: "PullRequest", title: "Fix login", url: null },
            { key: "Issue:2", type: "Issue", title: "fix login", url: null },
          ],
        }),
      ]),
    );
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    await screen.findByText("Contradicted");
    expect(screen.getByText("Fix login")).toBeInTheDocument();
    expect(screen.getByText("fix login")).toBeInTheDocument();
    expect(screen.getByText("High priority")).toBeInTheDocument();
  });

  it("keeps the server's order instead of sorting again", async () => {
    mockFlags(
      payload([
        flag({ id: "a", severity: "HIGH", summary: "Worst." }),
        flag({ id: "b", severity: "LOW", summary: "Least bad." }),
      ]),
    );
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    await screen.findByText("Worst.");
    // The flags themselves, not the target chips nested inside each one.
    const items = screen.getAllByRole("article");
    expect(items[0]).toHaveTextContent("Worst.");
    expect(items[1]).toHaveTextContent("Least bad.");
  });

  it("says when it last checked", async () => {
    mockFlags(payload([flag()]));
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByText(/checked/)).toBeInTheDocument();
  });

  it("says when it could only see part of a large workspace", async () => {
    mockFlags(payload([flag()], { truncated: true }));
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    expect(
      await screen.findByText(/larger than one check can cover/),
    ).toBeInTheDocument();
  });

  it("re-runs the check on request", async () => {
    const fetchFn = mockFlags(payload([]));
    const user = userEvent.setup();
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);
    await screen.findByText(/Nothing needs review/);

    await user.click(screen.getByRole("button", { name: "Check again" }));

    await waitFor(() => expect(fetchFn.mock.calls.length).toBeGreaterThan(1));
  });

  it("does not report an empty queue when the check failed", async () => {
    /** "Nothing needs review" and "we could not look" are different answers. */
    mockFlags({ detail: "Graph database unavailable" }, 503);
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Graph database unavailable",
    );
    expect(screen.queryByText(/Nothing needs review/)).not.toBeInTheDocument();
  });

  it("can retry after a failure", async () => {
    let calls = 0;
    const fetchFn = vi.fn(() => {
      calls += 1;
      return Promise.resolve(
        calls === 1
          ? jsonResponse({ detail: "Graph database unavailable" }, 503)
          : jsonResponse(payload([])),
      );
    });
    vi.stubGlobal("fetch", fetchFn);
    const user = userEvent.setup();
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);
    await screen.findByRole("alert");

    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByText(/Nothing needs review/)).toBeInTheDocument();
  });

  it("sends an unauthenticated visitor to log in", async () => {
    mockFlags({ detail: "Not authenticated" }, 401);
    render(<ReviewQueue workspaceId={WORKSPACE_ID} />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});
