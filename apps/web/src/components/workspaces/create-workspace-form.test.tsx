import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateWorkspaceForm } from "@/components/workspaces/create-workspace-form";

const router = { push: vi.fn(), replace: vi.fn(), refresh: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const CREATED = {
  id: "0b6f2c1e-8d43-4a36-9f59-2f1f6a1c9e11",
  name: "Apollo",
  description: "Launch plans",
  role: "OWNER",
  created_at: "2026-09-24T00:00:00Z",
};

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

async function submit(name: string, description = "") {
  const user = userEvent.setup();
  render(<CreateWorkspaceForm />);
  if (name) await user.type(screen.getByLabelText(/workspace name/i), name);
  if (description) {
    await user.type(screen.getByLabelText(/description/i), description);
  }
  await user.click(screen.getByRole("button", { name: /create workspace/i }));
}

beforeEach(() => {
  router.push.mockReset();
  router.replace.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("CreateWorkspaceForm", () => {
  it("posts the trimmed form and redirects to the new workspace", async () => {
    const fetchFn = mockFetch(201, CREATED);
    await submit("  Apollo  ", "Launch plans");

    await vi.waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(`/workspaces/${CREATED.id}`),
    );
    const [url, init] = fetchFn.mock.calls[0];
    expect(url).toBe("/api/workspaces");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      name: "Apollo",
      description: "Launch plans",
    });
  });

  it("sends a null description when it is left blank", async () => {
    const fetchFn = mockFetch(201, { ...CREATED, description: null });
    await submit("Apollo");

    await vi.waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(JSON.parse(fetchFn.mock.calls[0][1].body)).toEqual({
      name: "Apollo",
      description: null,
    });
  });

  it.each([
    ["", /enter a workspace name/i],
    ["   ", /enter a workspace name/i],
  ])("rejects %j without calling the API", async (name, message) => {
    const fetchFn = mockFetch(201, CREATED);
    await submit(name);

    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(fetchFn).not.toHaveBeenCalled();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("shows the server message for a duplicate name (409)", async () => {
    mockFetch(409, { detail: "You already have a workspace named 'Apollo'" });
    await submit("Apollo");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You already have a workspace named 'Apollo'",
    );
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /create workspace/i })).toBeEnabled();
  });

  it("shows a readable message for server-side validation errors (422)", async () => {
    mockFetch(422, { detail: [{ msg: "String should have at most 100 characters" }] });
    await submit("Apollo");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /check the workspace name and description/i,
    );
  });

  it("sends the user to login when the session has expired (401)", async () => {
    mockFetch(401, { detail: "Not authenticated" });
    await submit("Apollo");

    await vi.waitFor(() => expect(router.replace).toHaveBeenCalledWith("/login"));
    expect(router.push).not.toHaveBeenCalled();
  });

  it("shows an error when the server is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
    await submit("Apollo");

    expect(await screen.findByRole("alert")).toHaveTextContent(/unable to reach cortex/i);
  });

  it("disables the form while the request is in flight", async () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>(() => {})));
    await submit("Apollo");

    expect(screen.getByRole("button", { name: /creating/i })).toBeDisabled();
    expect(screen.getByLabelText(/workspace name/i)).toBeDisabled();
    expect(screen.getByLabelText(/description/i)).toBeDisabled();
  });
});
