import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RemoveSourceModal, type RemovalTarget } from "./remove-source-modal";
const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
const target: RemovalTarget = {
  source: {
    repo: "owner/repo",
    kind: "github",
    status: "SUCCESS",
    pull_requests: 8,
    issues: 3,
    total_items: 11,
    sections: 0,
    channels: 0,
    messages: 0,
    display_name: null,
    last_attempted_at: null,
    last_synced_at: null,
    last_error: null,
    last_error_code: null,
    last_synced_by: null,
    last_synced_by_name: null,
  },
};
function show(value = target) {
  const onClose = vi.fn(),
    onRemoved = vi.fn();
  render(
    <RemoveSourceModal
      workspaceId="ws"
      target={value}
      onClose={onClose}
      onRemoved={onRemoved}
    />,
  );
  return { onClose, onRemoved };
}
beforeEach(() => {
  replace.mockReset();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value() {
      this.setAttribute("open", "");
    },
  });
  Object.defineProperty(HTMLDialogElement.prototype, "close", {
    configurable: true,
    value() {
      this.removeAttribute("open");
    },
  });
});
afterEach(() => vi.unstubAllGlobals());
it("identifies the source and focuses Cancel", async () => {
  const { onClose } = show();
  expect(screen.getByRole("dialog", { name: "Remove source?" })).toBeVisible();
  expect(screen.getByText("owner/repo")).toBeVisible();
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onClose).toHaveBeenCalledOnce();
});
it("removes the exact channel and explains that the connection stays active", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const { onRemoved } = show({
    source: {
      ...target.source,
      kind: "slack",
      repo: "T123",
      display_name: "Team",
    },
    channel: { id: "slack/C1", name: "engineering", messages: 4 },
  });
  expect(screen.getByText(/connection stays active/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Remove channel" }));
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
    kind: "slack",
    external_ref: "T123",
    channel_id: "slack/C1",
  });
  expect(onRemoved).toHaveBeenCalledWith("#engineering");
});
it("prevents duplicate submission and dismissal while cleanup runs", async () => {
  let finish!: (value: Response) => void;
  const fetch = vi.fn(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  vi.stubGlobal("fetch", fetch);
  const { onClose, onRemoved } = show();
  await userEvent.click(screen.getByRole("button", { name: "Remove source" }));
  fireEvent.submit(
    screen.getByRole("button", { name: "Removing…" }).closest("form")!,
  );
  fireEvent(
    screen.getByRole("dialog"),
    new Event("cancel", { cancelable: true }),
  );
  expect(fetch).toHaveBeenCalledOnce();
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  await act(async () => finish(new Response(null, { status: 204 })));
  expect(onRemoved).toHaveBeenCalledOnce();
});
it("keeps failures open and allows a safe retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Offline"))
      .mockResolvedValueOnce(new Response(null, { status: 204 })),
  );
  const { onRemoved } = show();
  await userEvent.click(screen.getByRole("button", { name: "Remove source" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/Retrying safely/);
  expect(onRemoved).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Remove source" }));
  await waitFor(() => expect(onRemoved).toHaveBeenCalledOnce());
});
it.each([401, 403])("handles authorization failure %s", async (status) => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(Response.json({ detail: "Denied" }, { status })),
  );
  show();
  await userEvent.click(screen.getByRole("button", { name: "Remove source" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  if (status === 401) {
    await userEvent.click(
      screen.getByRole("button", { name: "Sign in again" }),
    );
    expect(replace).toHaveBeenCalledWith("/login");
  } else
    expect(
      screen.getByRole("button", { name: "Remove source" }),
    ).toBeDisabled();
});
