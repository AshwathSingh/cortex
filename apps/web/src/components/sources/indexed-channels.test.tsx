import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { IndexedChannels } from "./indexed-channels";
import type { WorkspaceSource } from "@/lib/api-types";

vi.mock("@/lib/api", () => ({
  ApiError: class extends Error {},
  apiRequest: vi.fn().mockResolvedValue([
    { id: "slack/one", name: "one", messages: 0, removal_pending: true },
    { id: "slack/two", name: "two", messages: 8 },
  ]),
}));

it("keeps a channel retry distinct from its surviving sibling", async () => {
  const source = { kind: "slack", repo: "team" } as WorkspaceSource;
  const onRemove = vi.fn();
  render(
    <IndexedChannels workspaceId="ws" source={source} onRemove={onRemove} />,
  );
  const retry = await screen.findByRole("button", {
    name: "Retry removal of #one",
  });
  expect(
    screen.getByText(
      "Removal incomplete. Retry this channel to finish cleanup.",
    ),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "Remove #two" })).toBeVisible();
  await userEvent.click(retry);
  expect(onRemove).toHaveBeenCalledWith(
    { source, channel: expect.objectContaining({ id: "slack/one" }) },
    retry,
  );
});
