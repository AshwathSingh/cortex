import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  InviteMemberModal,
  type InviteRoleOption,
} from "@/components/workspaces/invite-member-modal";

const ROLES: InviteRoleOption[] = [
  {
    key: "builtin:EDITOR",
    name: "Editor",
    description: "Can contribute sources",
    selection: { role: "EDITOR" },
    isDefault: true,
  },
  {
    key: "builtin:VIEWER",
    name: "Viewer",
    description: "Can view the workspace",
    selection: { role: "VIEWER" },
  },
];

const CREATED = {
  email: "teammate@example.com",
  role: "EDITOR",
  expires_at: "2026-11-10T12:00:00Z",
  token: "one-time-secret",
};

beforeEach(() => {
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

function renderModal(
  onInvite = vi.fn().mockResolvedValue(CREATED),
  overrides: Partial<React.ComponentProps<typeof InviteMemberModal>> = {},
) {
  const onClose = vi.fn();
  render(
    <InviteMemberModal
      workspaceName="Cortex Engineering"
      roles={ROLES}
      onClose={onClose}
      onInvite={onInvite}
      {...overrides}
    />,
  );
  return { onClose, onInvite };
}

describe("InviteMemberModal", () => {
  it("opens on the email field with a clear default role", () => {
    renderModal();

    expect(screen.getByRole("dialog", { name: "Invite a member" })).toBeVisible();
    expect(screen.getByLabelText("Email address")).toHaveFocus();
    expect(screen.getByLabelText("Workspace role")).toHaveValue(
      "builtin:EDITOR",
    );
  });

  it("submits the email and selected role once", async () => {
    const user = userEvent.setup();
    const onInvite = vi.fn().mockResolvedValue(CREATED);
    renderModal(onInvite);

    await user.type(
      screen.getByLabelText("Email address"),
      "teammate@example.com",
    );
    await user.selectOptions(
      screen.getByLabelText("Workspace role"),
      "builtin:VIEWER",
    );
    await user.click(screen.getByRole("button", { name: "Create invite" }));

    expect(onInvite).toHaveBeenCalledWith("teammate@example.com", {
      role: "VIEWER",
    });
    expect(
      await screen.findByRole("heading", { name: "Invite created" }),
    ).toBeInTheDocument();
  });

  it("keeps the form available and shows an API error", async () => {
    const user = userEvent.setup();
    renderModal(
      vi.fn().mockRejectedValue(
        new Error("teammate@example.com already has a pending invitation"),
      ),
    );

    await user.type(
      screen.getByLabelText("Email address"),
      "teammate@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Create invite" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "already has a pending invitation",
    );
    expect(screen.getByLabelText("Email address")).toHaveValue(
      "teammate@example.com",
    );
    expect(screen.getByRole("button", { name: "Create invite" })).toBeEnabled();
  });

  it("keeps the private acceptance link visible until it is copied", async () => {
    const user = userEvent.setup();
    const writeText = vi
      .spyOn(navigator.clipboard, "writeText")
      .mockResolvedValue(undefined);
    renderModal();

    await user.type(
      screen.getByLabelText("Email address"),
      "teammate@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Create invite" }));
    await user.click(await screen.findByRole("button", { name: "Copy link" }));

    const inviteLink =
      "http://localhost:3000/invites/accept#token=one-time-secret";
    expect(writeText).toHaveBeenCalledWith(inviteLink);
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(screen.getByDisplayValue(inviteLink)).toBeInTheDocument();
  });

  it("offers visible and keyboard dismissal", async () => {
    const user = userEvent.setup();
    const { onClose } = renderModal();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    const second = renderModal();
    fireEvent(
      screen.getByRole("dialog"),
      new Event("cancel", { bubbles: false, cancelable: true }),
    );
    expect(second.onClose).toHaveBeenCalledTimes(1);
  });
});
