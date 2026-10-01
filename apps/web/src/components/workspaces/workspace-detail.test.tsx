import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceDetail } from "@/components/workspaces/workspace-detail";

const router = { replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const WORKSPACE = {
  id: "workspace-1",
  name: "Cortex Engineering",
  description: null,
  role: "OWNER",
  created_at: "2026-09-28T00:00:00Z",
};

function mockFetch(status = 200, body: unknown = WORKSPACE) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    ),
  );
}

beforeEach(() => {
  router.replace.mockReset();
  window.sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("WorkspaceDetail", () => {
  it("loads the workspace into the Cortex composer", async () => {
    mockFetch();

    render(<WorkspaceDetail workspaceId={WORKSPACE.id} />);

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(
      WORKSPACE.name,
    );
    expect(
      screen.getByRole("link", {
        name: `Switch workspace. Current workspace: ${WORKSPACE.name}`,
      }),
    ).toHaveTextContent(WORKSPACE.name);
    expect(screen.getByLabelText(/ask cortex about this workspace/i)).toBeEnabled();
    expect(screen.getByRole("button", { name: /send question/i })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("uses a different heading when a new page session begins", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    mockFetch();

    const firstPage = render(<WorkspaceDetail workspaceId={WORKSPACE.id} />);
    await screen.findByRole("link", {
      name: `Switch workspace. Current workspace: ${WORKSPACE.name}`,
    });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "What should we explore in",
    );
    firstPage.unmount();

    render(<WorkspaceDetail workspaceId={WORKSPACE.id} />);
    await vi.waitFor(() =>
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
        "What would you like to understand about",
      ),
    );
  });

  it("places a suggested question into the composer", async () => {
    mockFetch();
    const user = userEvent.setup();
    render(<WorkspaceDetail workspaceId={WORKSPACE.id} />);

    await user.click(
      screen.getByRole("button", { name: "Show open contradictions" }),
    );

    expect(screen.getByLabelText(/ask cortex about this workspace/i)).toHaveValue(
      "Show open contradictions",
    );
    expect(screen.getByRole("button", { name: /send question/i })).toHaveAttribute(
      "aria-disabled",
      "false",
    );
  });

  it("explains that assistant responses are not connected yet", async () => {
    mockFetch();
    const user = userEvent.setup();
    render(<WorkspaceDetail workspaceId={WORKSPACE.id} />);

    await user.type(
      screen.getByLabelText(/ask cortex about this workspace/i),
      "Why Neo4j?",
    );
    await user.click(screen.getByRole("button", { name: /send question/i }));

    expect(screen.getByText(/assistant service is connected/i)).toBeInTheDocument();
  });

  it("returns expired sessions to login", async () => {
    mockFetch(401, { detail: "Not authenticated" });

    render(<WorkspaceDetail workspaceId={WORKSPACE.id} />);

    await vi.waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
  });
});
