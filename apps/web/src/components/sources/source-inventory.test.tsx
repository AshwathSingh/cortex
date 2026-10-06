import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SourceInventory } from "@/components/sources/source-inventory";
import { WorkspaceProvider } from "@/components/workspaces/workspace-context";
import type { WorkspaceRole } from "@/lib/api-types";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

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
    mockFetch(200, [{ repo: "openai/cortex", pull_requests: 8, issues: 3, total_items: 11 }]);
    renderInventory();
    const repository = await screen.findByRole("link", { name: /openai\/cortex/i });
    expect(repository).toHaveAttribute("href", "https://github.com/openai/cortex");
    expect(screen.getByText("1 source · 11 items indexed")).toBeInTheDocument();
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
    const fetchFn = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Workspace access denied" }), { status: 403, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchFn);
    const user = userEvent.setup();
    renderInventory();
    expect(await screen.findByRole("alert")).toHaveTextContent(/access denied/i);
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText(/connect your first source/i)).toBeInTheDocument();
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  it("redirects unauthenticated users to login", async () => {
    mockFetch(401, { detail: "Not authenticated" });
    renderInventory();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});
