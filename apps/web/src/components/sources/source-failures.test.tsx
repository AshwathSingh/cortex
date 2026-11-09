import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SourceFailureBanner,
  SourceFailureList,
} from "@/components/sources/source-failures";
import type { SourceFailure } from "@/lib/api-types";

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

function failure(over: Partial<SourceFailure> = {}): SourceFailure {
  return {
    repo: "openai/cortex",
    kind: "github",
    category: "AUTH",
    label: "Authorization expired",
    message: "GitHub rejected this workspace's credentials; sign in again",
    advice: "Sign in to GitHub again to refresh this workspace's access.",
    needs_reauth: true,
    can_retry: false,
    last_attempted_at: minutesAgo(2),
    last_synced_at: minutesAgo(180),
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

beforeEach(() => replace.mockClear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("SourceFailureBanner (AC1)", () => {
  it("says nothing when every source is healthy", () => {
    const { container } = render(
      <SourceFailureBanner workspaceId={WORKSPACE_ID} failures={[]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("names the source and its problem when one is broken", () => {
    render(
      <SourceFailureBanner workspaceId={WORKSPACE_ID} failures={[failure()]} />,
    );

    expect(screen.getByText("1 source needs attention.")).toBeInTheDocument();
    expect(
      screen.getByText("openai/cortex: authorization expired."),
    ).toBeInTheDocument();
  });

  it("counts them when several are broken", () => {
    render(
      <SourceFailureBanner
        workspaceId={WORKSPACE_ID}
        failures={[failure(), failure({ repo: "openai/other" })]}
      />,
    );

    expect(screen.getByText("2 sources need attention.")).toBeInTheDocument();
  });

  it("links to the page that can fix them", () => {
    render(
      <SourceFailureBanner workspaceId={WORKSPACE_ID} failures={[failure()]} />,
    );

    expect(screen.getByRole("link", { name: "Review sources" })).toHaveAttribute(
      "href",
      `/workspaces/${WORKSPACE_ID}/sources`,
    );
  });
});

describe("SourceFailureList (AC2, AC4)", () => {
  function renderList(failures: SourceFailure[], onChanged = vi.fn()) {
    render(
      <SourceFailureList
        workspaceId={WORKSPACE_ID}
        failures={failures}
        onChanged={onChanged}
      />,
    );
    return { onChanged };
  }

  it("shows the recorded message and what to do about it", () => {
    renderList([failure()]);

    expect(screen.getByText("Authorization expired")).toBeInTheDocument();
    expect(screen.getByText(/GitHub rejected this workspace/)).toBeInTheDocument();
    expect(screen.getByText(/Sign in to GitHub again/)).toBeInTheDocument();
  });

  it("offers the GitHub sign-in flow for an expired authorization", () => {
    renderList([failure()]);

    expect(screen.getByRole("link", { name: "Reconnect GitHub" })).toHaveAttribute(
      "href",
      "/api/auth/github/login",
    );
  });

  it("offers no retry when retrying would fail the same way", () => {
    renderList([failure({ needs_reauth: true, can_retry: false })]);

    expect(
      screen.queryByRole("button", { name: /try .* again/i }),
    ).not.toBeInTheDocument();
  });

  it("offers a retry and no sign-in for a rate limit", () => {
    renderList([
      failure({
        category: "RATE_LIMIT",
        label: "Too many requests",
        needs_reauth: false,
        can_retry: true,
      }),
    ]);

    expect(
      screen.getByRole("button", { name: "Try openai/cortex again" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Reconnect GitHub" }),
    ).not.toBeInTheDocument();
  });

  it("says how stale the data it is still showing is", () => {
    renderList([failure({ last_synced_at: minutesAgo(180) })]);

    expect(
      screen.getByText(/Showing data from 3 hours ago, synced by Ashwath/),
    ).toBeInTheDocument();
  });

  it("says plainly when a source has never worked", () => {
    renderList([failure({ last_synced_at: null, last_synced_by_name: null })]);

    expect(
      screen.getByText(/Never synced successfully/),
    ).toBeInTheDocument();
  });

  it("re-ingests the source when retried", async () => {
    const fetchFn = vi.fn(() => Promise.resolve(jsonResponse({ repo: "openai/cortex" })));
    vi.stubGlobal("fetch", fetchFn);
    const user = userEvent.setup();
    const { onChanged } = renderList([
      failure({ category: "UPSTREAM", needs_reauth: false, can_retry: true }),
    ]);

    await user.click(screen.getByRole("button", { name: "Try openai/cortex again" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/ingest/github");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      repo_url: "https://github.com/openai/cortex",
      workspace_id: WORKSPACE_ID,
    });
  });

  it("holds every other retry while one ingestion runs", async () => {
    /** Ingestion is heavy and shares the workspace's GitHub rate limit, so two
     *  at once would have the second re-spend what the first is using. */
    let resolveIngest: (value: Response) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (resolveIngest = resolve))),
    );
    const user = userEvent.setup();
    renderList([
      failure({ category: "UPSTREAM", needs_reauth: false, can_retry: true }),
      failure({
        repo: "openai/other",
        category: "UPSTREAM",
        needs_reauth: false,
        can_retry: true,
      }),
    ]);

    await user.click(screen.getByRole("button", { name: "Try openai/cortex again" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Try openai/other again" })).toBeDisabled(),
    );
    resolveIngest(jsonResponse({ repo: "openai/cortex" }));
  });

  it("reports a retry that never reached Cortex", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    const user = userEvent.setup();
    renderList([failure({ category: "GRAPH", needs_reauth: false, can_retry: true })]);

    await user.click(screen.getByRole("button", { name: "Try openai/cortex again" }));

    expect(
      await screen.findByText(/Could not reach Cortex to re-sync openai\/cortex/),
    ).toBeInTheDocument();
  });

  it("sends an unauthenticated visitor to log in", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ detail: "Not authenticated" }, 401))),
    );
    const user = userEvent.setup();
    renderList([failure({ category: "UPSTREAM", needs_reauth: false, can_retry: true })]);

    await user.click(screen.getByRole("button", { name: "Try openai/cortex again" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("renders nothing when there is nothing broken", () => {
    const { container } = render(
      <SourceFailureList
        workspaceId={WORKSPACE_ID}
        failures={[]}
        onChanged={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
