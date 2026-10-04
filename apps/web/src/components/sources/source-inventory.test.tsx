import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SourceInventory } from "@/components/sources/source-inventory";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

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
    render(<SourceInventory workspaceId={WORKSPACE_ID} />);
    await screen.findByText(/connect your first source/i);
    expect(fetchFn.mock.calls[0][0]).toBe(`/api/workspaces/${WORKSPACE_ID}/sources`);
  });

  it("shows connected repositories and their indexed counts", async () => {
    mockFetch(200, [{ repo: "openai/cortex", pull_requests: 8, issues: 3, total_items: 11 }]);
    render(<SourceInventory workspaceId={WORKSPACE_ID} />);
    const repository = await screen.findByRole("link", { name: /openai\/cortex/i });
    expect(repository).toHaveAttribute("href", "https://github.com/openai/cortex");
    expect(screen.getByText("1 source · 11 items indexed")).toBeInTheDocument();
  });

  it("offers repository ingestion in an empty workspace", async () => {
    mockFetch(200, []);
    render(<SourceInventory workspaceId={WORKSPACE_ID} />);
    expect(await screen.findByRole("link", { name: /add github repository/i })).toHaveAttribute("href", `/workspaces/${WORKSPACE_ID}/ingest`);
  });

  it("shows access errors and can retry", async () => {
    const fetchFn = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Workspace access denied" }), { status: 403, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchFn);
    const user = userEvent.setup();
    render(<SourceInventory workspaceId={WORKSPACE_ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/access denied/i);
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText(/connect your first source/i)).toBeInTheDocument();
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  it("redirects unauthenticated users to login", async () => {
    mockFetch(401, { detail: "Not authenticated" });
    render(<SourceInventory workspaceId={WORKSPACE_ID} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});
