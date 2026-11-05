import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GraphComments } from "@/components/graph/graph-comments";
import type { GraphComment } from "@/lib/api-types";
import type { CommentTargetRef } from "@/lib/graph-comment-target";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";
const ME = "11111111-0000-4000-8000-000000000001";
const SOMEONE_ELSE = "11111111-0000-4000-8000-000000000002";

const NODE: CommentTargetRef = { target_kind: "node", target_key: "Issue:42" };
const EDGE: CommentTargetRef = {
  target_kind: "edge",
  target_key: "Author:7|AUTHORED|Issue:42",
};

const { replace, routerMock } = vi.hoisted(() => {
  const replaceFn = vi.fn();
  return {
    replace: replaceFn,
    routerMock: { replace: replaceFn, push: vi.fn(), refresh: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function comment(over: Partial<GraphComment> = {}): GraphComment {
  return {
    id: "aaaaaaa0-0000-4000-8000-00000000000a",
    target_kind: "node",
    target_key: "Issue:42",
    body: "This looks wrong to me.",
    author_id: SOMEONE_ELSE,
    author_name: "Ashwath",
    created_at: minutesAgo(10),
    ...over,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type Routes = {
  thread?: GraphComment[];
  threadStatus?: number;
  onPost?: () => Promise<Response>;
  onDelete?: () => Promise<Response>;
};

/** Routes the four endpoints a thread touches, by URL and method. */
function mockApi({ thread = [], threadStatus = 200, onPost, onDelete }: Routes = {}) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/comments/seen")) return Promise.resolve(jsonResponse({}));
    if (method === "DELETE") {
      return onDelete ? onDelete() : Promise.resolve(new Response(null, { status: 204 }));
    }
    if (method === "POST") {
      return onPost
        ? onPost()
        : Promise.resolve(jsonResponse(comment({ body: "posted" }), 201));
    }
    return Promise.resolve(jsonResponse(thread, threadStatus));
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderThread(target: CommentTargetRef = NODE, currentUserId: string | null = ME) {
  const onActivityChange = vi.fn();
  render(
    <GraphComments
      workspaceId={WORKSPACE_ID}
      target={target}
      currentUserId={currentUserId}
      onActivityChange={onActivityChange}
    />,
  );
  return { onActivityChange };
}

beforeEach(() => replace.mockClear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("reading a thread (AC1)", () => {
  it("asks for its own target's comments", async () => {
    const fetchFn = mockApi();
    renderThread(EDGE);

    await screen.findByText(/No comments yet/);

    const url = String(fetchFn.mock.calls[0][0]);
    expect(url).toContain(`/api/workspaces/${WORKSPACE_ID}/graph/comments?`);
    expect(url).toContain("target_kind=edge");
    expect(decodeURIComponent(url)).toContain("target_key=Author:7|AUTHORED|Issue:42");
  });

  it("lists comments in the order they were made, with author and time", async () => {
    mockApi({
      thread: [
        comment({ id: "1", body: "first", author_name: "Ashwath", created_at: minutesAgo(60) }),
        comment({ id: "2", body: "second", author_name: "Aryan", created_at: minutesAgo(5) }),
      ],
    });
    renderThread();

    const items = await screen.findAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("first"),
      expect.stringContaining("second"),
    ]);
    expect(items[0]).toHaveTextContent("Ashwath");
    expect(items[0]).toHaveTextContent("1 hour ago");
    expect(items[1]).toHaveTextContent("Aryan");
  });

  it("counts the thread in its heading", async () => {
    mockApi({ thread: [comment({ id: "1" }), comment({ id: "2" })] });
    renderThread();

    expect(await screen.findByText("Comments (2)")).toBeInTheDocument();
  });

  it("says plainly when nobody has commented", async () => {
    mockApi();
    renderThread();

    expect(await screen.findByText(/No comments yet/)).toBeInTheDocument();
  });

  it("attributes a comment whose author has left without inventing a name", async () => {
    mockApi({ thread: [comment({ author_id: null, author_name: null })] });
    renderThread();

    expect(await screen.findByText("Former member")).toBeInTheDocument();
  });

  it("reports a thread it could not load", async () => {
    mockApi({ thread: [], threadStatus: 503 });
    renderThread();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("marking a thread read (T-27.4)", () => {
  it("marks the target seen once its comments are on screen", async () => {
    const fetchFn = mockApi({ thread: [comment()] });
    const { onActivityChange } = renderThread();

    await screen.findByText("This looks wrong to me.");

    await waitFor(() =>
      expect(
        fetchFn.mock.calls.some(([url]) => String(url).includes("/comments/seen")),
      ).toBe(true),
    );
    await waitFor(() => expect(onActivityChange).toHaveBeenCalled());
  });

  it("marks nothing seen on an empty thread", async () => {
    const fetchFn = mockApi();
    renderThread();

    await screen.findByText(/No comments yet/);

    expect(
      fetchFn.mock.calls.some(([url]) => String(url).includes("/comments/seen")),
    ).toBe(false);
  });
});

describe("posting", () => {
  it("sends the comment against the selected target", async () => {
    const fetchFn = mockApi();
    const user = userEvent.setup();
    const { onActivityChange } = renderThread();
    await screen.findByText(/No comments yet/);

    await user.type(screen.getByLabelText("Add a comment"), "Needs evidence.");
    await user.click(screen.getByRole("button", { name: "Comment" }));

    const post = fetchFn.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "POST",
    );
    expect(JSON.parse(String((post?.[1] as RequestInit).body))).toEqual({
      target_kind: "node",
      target_key: "Issue:42",
      body: "Needs evidence.",
    });
    await waitFor(() => expect(onActivityChange).toHaveBeenCalled());
  });

  it("will not send an empty comment", async () => {
    mockApi();
    renderThread();
    await screen.findByText(/No comments yet/);

    expect(screen.getByRole("button", { name: "Comment" })).toBeDisabled();
  });

  it("will not send whitespace", async () => {
    mockApi();
    const user = userEvent.setup();
    renderThread();
    await screen.findByText(/No comments yet/);

    await user.type(screen.getByLabelText("Add a comment"), "   ");

    expect(screen.getByRole("button", { name: "Comment" })).toBeDisabled();
  });

  it("clears the box and reloads the thread after posting", async () => {
    const fetchFn = mockApi();
    const user = userEvent.setup();
    renderThread();
    await screen.findByText(/No comments yet/);
    const reads = fetchFn.mock.calls.filter(
      ([url, init]) =>
        (init as RequestInit | undefined)?.method === undefined &&
        String(url).includes("/graph/comments?"),
    ).length;

    await user.type(screen.getByLabelText("Add a comment"), "Done.");
    await user.click(screen.getByRole("button", { name: "Comment" }));

    await waitFor(() =>
      expect(
        fetchFn.mock.calls.filter(
          ([url, init]) =>
            (init as RequestInit | undefined)?.method === undefined &&
            String(url).includes("/graph/comments?"),
        ).length,
      ).toBeGreaterThan(reads),
    );
    expect(screen.getByLabelText("Add a comment")).toHaveValue("");
  });

  it("keeps the draft and says why when the post is refused", async () => {
    mockApi({
      onPost: () =>
        Promise.resolve(jsonResponse({ detail: "A comment cannot be empty" }, 422)),
    });
    const user = userEvent.setup();
    renderThread();
    await screen.findByText(/No comments yet/);

    await user.type(screen.getByLabelText("Add a comment"), "Something");
    await user.click(screen.getByRole("button", { name: "Comment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("A comment cannot be empty");
    expect(screen.getByLabelText("Add a comment")).toHaveValue("Something");
  });

  it("reports a post that never reached Cortex", async () => {
    mockApi({ onPost: () => Promise.reject(new TypeError("Failed to fetch")) });
    const user = userEvent.setup();
    renderThread();
    await screen.findByText(/No comments yet/);

    await user.type(screen.getByLabelText("Add a comment"), "Something");
    await user.click(screen.getByRole("button", { name: "Comment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/server is unreachable/);
  });
});

describe("deleting", () => {
  it("offers delete on your own comment only", async () => {
    mockApi({
      thread: [
        comment({ id: "mine", body: "mine", author_id: ME, author_name: "Aryan" }),
        comment({ id: "theirs", body: "theirs", author_id: SOMEONE_ELSE }),
      ],
    });
    renderThread();

    await screen.findByText("mine");
    expect(screen.getAllByRole("button", { name: "Delete comment" })).toHaveLength(1);
  });

  it("offers no delete at all when the reader is unknown", async () => {
    mockApi({ thread: [comment({ author_id: ME })] });
    renderThread(NODE, null);

    await screen.findByText("This looks wrong to me.");
    expect(
      screen.queryByRole("button", { name: "Delete comment" }),
    ).not.toBeInTheDocument();
  });

  it("removes the comment and refreshes the badges", async () => {
    const fetchFn = mockApi({ thread: [comment({ id: "mine", author_id: ME })] });
    const user = userEvent.setup();
    const { onActivityChange } = renderThread();
    await screen.findByText("This looks wrong to me.");
    onActivityChange.mockClear();

    await user.click(screen.getByRole("button", { name: "Delete comment" }));

    await waitFor(() =>
      expect(
        fetchFn.mock.calls.some(
          ([, init]) => (init as RequestInit | undefined)?.method === "DELETE",
        ),
      ).toBe(true),
    );
    await waitFor(() => expect(onActivityChange).toHaveBeenCalled());
  });

  it("says why a delete was refused", async () => {
    mockApi({
      thread: [comment({ id: "mine", author_id: ME })],
      onDelete: () =>
        Promise.resolve(jsonResponse({ detail: "You can only delete your own comments" }, 403)),
    });
    const user = userEvent.setup();
    renderThread();
    await screen.findByText("This looks wrong to me.");

    await user.click(screen.getByRole("button", { name: "Delete comment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("your own comments");
  });
});

describe("authentication", () => {
  it("sends an unauthenticated visitor to log in", async () => {
    mockApi({ thread: [], threadStatus: 401 });
    renderThread();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});
