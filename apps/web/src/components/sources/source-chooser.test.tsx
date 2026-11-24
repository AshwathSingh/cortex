import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { SourceChooser } from "./source-chooser";
import { WorkspaceProvider } from "@/components/workspaces/workspace-context";
import type { SourceOptions } from "@/lib/api-types";
const { replace, router } = vi.hoisted(() => { const replace = vi.fn(); return { replace, router: { replace } }; });
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const OPTIONS: SourceOptions = {
  can_manage_sources: true,
  providers: ["github", "upload", "slack", "discord"].map((kind) => ({
    kind: kind as SourceOptions["providers"][number]["kind"],
    available: true,
    reason: null,
  })),
};
function page(id = "one", mayManage = true) {
  return (
    <WorkspaceProvider
      value={{
        workspaceId: id,
        workspace: {
          id,
          name: "Cortex",
          description: null,
          role: "VIEWER",
          permissions: mayManage ? ["sources.write"] : [],
          created_at: "2026-11-24",
        },
        isLoading: false,
        user: null,
        error: null,
      }}
    >
      <SourceChooser workspaceId={id} />
    </WorkspaceProvider>
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
});
it("offers all source types and links to each connection flow", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(OPTIONS)));
  render(page());
  expect(
    await screen.findByRole("link", { name: "Add repository" }),
  ).toHaveAttribute("href", "/workspaces/one/ingest");
  expect(
    screen.getByRole("link", { name: "Upload a document" }),
  ).toHaveAttribute("href", "/workspaces/one/sources#documents");
  expect(screen.getByRole("link", { name: "Set up Slack" })).toHaveAttribute(
    "href",
    "/workspaces/one/sources#slack",
  );
  expect(screen.getByRole("link", { name: "Set up Discord" })).toHaveAttribute(
    "href",
    "/workspaces/one/sources#discord",
  );
  expect(
    within(screen.getByRole("list", { name: "Source types" })).getAllByRole(
      "listitem",
    ),
  ).toHaveLength(4);
});
it("explains an unconfigured provider and does not offer its action", async () => {
  const options = {
    ...OPTIONS,
    providers: OPTIONS.providers.map((p) =>
      p.kind === "slack"
        ? {
            ...p,
            available: false,
            reason: "Slack is not configured on this server.",
          }
        : p,
    ),
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(options)));
  render(page());
  expect(
    await screen.findByText("Slack is not configured on this server."),
  ).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "Set up Slack" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Upload a document" })).toBeVisible();
});
it("shows provider-neutral guidance and no actions for viewers", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        Response.json({ ...OPTIONS, can_manage_sources: false }),
      ),
  );
  render(page("one", false));
  await screen.findAllByText("Source management access required");
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(
    screen.getByText(/add a repository, document or chat channel/),
  ).toBeVisible();
});
it("honors a server-side permission revocation even when context is stale", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        Response.json({ ...OPTIONS, can_manage_sources: false }),
      ),
  );
  render(page());
  expect(await screen.findByText(/access has changed/)).toBeVisible();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
it("keeps actions unavailable until configuration has loaded", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => {})),
  );
  render(page());
  expect(screen.getByRole("status")).toHaveTextContent(
    /Checking source availability/,
  );
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
it("shows availability errors and retries without losing the source list", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Offline"))
      .mockResolvedValueOnce(Response.json(OPTIONS)),
  );
  render(page());
  expect(await screen.findByRole("alert")).toHaveTextContent(/Unable to check/);
  expect(
    screen.getByRole("heading", { name: "Document upload" }),
  ).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "Retry source availability" }),
  );
  expect(
    await screen.findByRole("link", { name: "Set up Discord" }),
  ).toBeVisible();
});
it("discards a late availability response from the previous workspace", async () => {
  let first!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            first = resolve;
          }),
      )
      .mockResolvedValue(
        Response.json({ ...OPTIONS, can_manage_sources: false }),
      ),
  );
  const view = render(page("one"));
  view.rerender(page("two"));
  await screen.findByText(/access has changed/);
  await act(async () => first(Response.json(OPTIONS)));
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
it("treats malformed availability data as an error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json([])));
  render(page());
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
