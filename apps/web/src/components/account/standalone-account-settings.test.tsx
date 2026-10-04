import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StandaloneAccountSettings } from "@/components/account/standalone-account-settings";

const router = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn() };

vi.mock("next/navigation", () => ({ useRouter: () => router }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("StandaloneAccountSettings", () => {
  it("returns to the explicit workspace selector", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>(() => {})));

    render(<StandaloneAccountSettings />);

    expect(screen.getByRole("link", { name: /all workspaces/i })).toHaveAttribute(
      "href",
      "/workspaces?select=1",
    );
  });
});
