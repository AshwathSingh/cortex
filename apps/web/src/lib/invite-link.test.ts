import { beforeEach, describe, expect, it } from "vitest";

import {
  capturePendingInviteToken,
  clearPendingInviteToken,
  createInviteLink,
  postAuthDestination,
} from "@/lib/invite-link";

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
});

describe("invite links", () => {
  it("puts the secret in a URL fragment instead of the request path", () => {
    expect(createInviteLink("https://cortex.example", "secret + value")).toBe(
      "https://cortex.example/invites/accept#token=secret+%2B+value",
    );
  });

  it("captures the fragment for authentication and removes it from the address bar", () => {
    window.history.replaceState(
      {},
      "",
      "/invites/accept#token=one-time-secret",
    );

    expect(capturePendingInviteToken()).toBe("one-time-secret");
    expect(window.location.href).toBe("http://localhost:3000/invites/accept");
    expect(postAuthDestination()).toBe("/invites/accept");
  });

  it("clears the post-auth destination after acceptance", () => {
    window.history.replaceState({}, "", "/invites/accept#token=secret");
    capturePendingInviteToken();

    clearPendingInviteToken();

    expect(postAuthDestination()).toBe("/workspaces");
  });
});
