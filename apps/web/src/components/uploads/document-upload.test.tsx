import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { DocumentUpload } from "@/components/uploads/document-upload";

const WORKSPACE_ID = "ccccccc0-0000-4000-8000-00000000c0de";

const { replace, routerMock } = vi.hoisted(() => {
  const replaceFn = vi.fn();
  return {
    replace: replaceFn,
    routerMock: { replace: replaceFn, push: vi.fn(), refresh: vi.fn() },
  };
});

vi.mock("next/navigation", () => ({ useRouter: () => routerMock }));

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockUpload(
  handler: () => Promise<Response> = () =>
    Promise.resolve(
      json(
        { filename: "prd.md", format: "text", sections: 2, replaced: false },
        201,
      ),
    ),
) {
  const fn = vi.fn(() => handler());
  vi.stubGlobal("fetch", fn);
  return fn;
}

function file(name = "prd.md", content = "# Scope\n\nIngestion only.\n") {
  return new File([content], name, { type: "text/markdown" });
}

function renderUpload(onUploaded = vi.fn()) {
  const utils = render(
    <DocumentUpload workspaceId={WORKSPACE_ID} onUploaded={onUploaded} />,
  );
  // The input is visually hidden but is the real control; the label wraps it.
  const input = utils.container.querySelector("input[type=file]")!;
  return { ...utils, input: input as HTMLInputElement, onUploaded };
}

beforeEach(() => {
  replace.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("accepts the three formats the backend can read", () => {
  mockUpload();
  const { input } = renderUpload();

  for (const suffix of [".pdf", ".docx", ".txt", ".md"]) {
    expect(input.accept).toContain(suffix);
  }
});

it("uploads a chosen file as multipart form data", async () => {
  const fetchFn = mockUpload();
  const { input, onUploaded } = renderUpload();

  await userEvent.upload(input, file());

  await waitFor(() => expect(onUploaded).toHaveBeenCalled());
  const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe(`/api/workspaces/${WORKSPACE_ID}/uploads`);
  expect(init.method).toBe("POST");
  expect(init.body).toBeInstanceOf(FormData);
  // No Content-Type: the browser has to set the multipart boundary itself.
  expect(new Headers(init.headers).get("Content-Type")).toBeNull();
  expect((init.body as FormData).get("file")).toBeInstanceOf(File);
});

it("reports how many sections were indexed", async () => {
  mockUpload();
  const { input } = renderUpload();

  await userEvent.upload(input, file());

  expect(
    await screen.findByText("Added prd.md — 2 sections indexed."),
  ).toBeInTheDocument();
});

it("says a re-upload replaced the previous copy", async () => {
  mockUpload(() =>
    Promise.resolve(
      json({ filename: "prd.md", format: "text", sections: 1, replaced: true }, 201),
    ),
  );
  const { input } = renderUpload();

  await userEvent.upload(input, file());

  expect(
    await screen.findByText("Replaced prd.md — 1 section indexed."),
  ).toBeInTheDocument();
});

it("shows the server's reason when a file is refused", async () => {
  /**
   * Dropped rather than chosen: the input's `accept` filter keeps an
   * unsupported file out of the picker, but a drop bypasses it entirely --
   * which is exactly why the server's check is the one that matters.
   */
  mockUpload(() =>
    Promise.resolve(
      json(
        {
          detail:
            "design.sketch is not a supported file type. Upload a PDF, a Word document (.docx), or a text file.",
        },
        415,
      ),
    ),
  );
  const { container } = renderUpload();

  fireEvent.drop(container.querySelector("label")!, {
    dataTransfer: { files: [file("design.sketch", "anything")] },
  });

  expect(
    await screen.findByText(/not a supported file type/),
  ).toBeInTheDocument();
});

it("shows the size limit when a file is too large", async () => {
  mockUpload(() =>
    Promise.resolve(json({ detail: "huge.txt is 12.0 MB, over the 10 MB limit." }, 413)),
  );
  const { input } = renderUpload();

  await userEvent.upload(input, file("huge.txt", "x".repeat(32)));

  expect(await screen.findByText(/over the 10 MB limit/)).toBeInTheDocument();
});

it("does not claim success when the request never reached Cortex", async () => {
  mockUpload(() => Promise.reject(new TypeError("Failed to fetch")));
  const { input, onUploaded } = renderUpload();

  await userEvent.upload(input, file());

  expect(
    await screen.findByText(/The Cortex server is unreachable/),
  ).toBeInTheDocument();
  expect(onUploaded).not.toHaveBeenCalled();
});

it("uploads a dropped file", async () => {
  const fetchFn = mockUpload();
  const { container } = renderUpload();
  const zone = container.querySelector("label")!;

  fireEvent.drop(zone, { dataTransfer: { files: [file()] } });

  await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(1));
});

it("ignores a drop with no files", async () => {
  const fetchFn = mockUpload();
  const { container } = renderUpload();
  const zone = container.querySelector("label")!;

  fireEvent.drop(zone, { dataTransfer: { files: [] } });

  expect(fetchFn).not.toHaveBeenCalled();
});

it("keeps the drop zone highlighted while the pointer crosses its children", async () => {
  /**
   * dragleave fires on every child boundary, so a boolean flag would flicker
   * the highlight off while the file is still over the zone.
   */
  mockUpload();
  const { container } = renderUpload();
  const zone = container.querySelector("label")!;

  fireEvent.dragEnter(zone);
  fireEvent.dragEnter(zone); // entered a child
  fireEvent.dragLeave(zone); // left that child, still inside the zone

  expect(zone.className).toContain("border-accent");

  fireEvent.dragLeave(zone);
  expect(zone.className).not.toContain("border-accent");
});

it("uploads several files one at a time", async () => {
  /** The request parses and writes the graph before answering, so firing a
   *  folder's worth at once would open as many parallel parses. */
  const seen: number[] = [];
  let inFlight = 0;
  const fetchFn = vi.fn(() => {
    inFlight += 1;
    seen.push(inFlight);
    return new Promise<Response>((resolve) =>
      setTimeout(() => {
        inFlight -= 1;
        resolve(
          json({ filename: "a.md", format: "text", sections: 1, replaced: false }, 201),
        );
      }, 5),
    );
  });
  vi.stubGlobal("fetch", fetchFn);
  const { input } = renderUpload();

  await userEvent.upload(input, [file("a.md"), file("b.md"), file("c.md")]);

  await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(3));
  expect(Math.max(...seen)).toBe(1);
});

it("lets the same file be chosen again after a failure", async () => {
  mockUpload(() => Promise.resolve(json({ detail: "unreadable" }, 422)));
  const { input } = renderUpload();

  await userEvent.upload(input, file());
  await screen.findByText("unreadable");

  expect(input.value).toBe("");
});

it("can clear what it has reported", async () => {
  mockUpload();
  const { input } = renderUpload();
  await userEvent.upload(input, file());
  await screen.findByText(/Added prd.md/);

  await userEvent.click(screen.getByRole("button", { name: "Clear" }));

  expect(screen.queryByText(/Added prd.md/)).not.toBeInTheDocument();
});

it("sends an unauthenticated visitor to log in", async () => {
  mockUpload(() => Promise.resolve(json({ detail: "Not authenticated" }, 401)));
  const { input } = renderUpload();

  await userEvent.upload(input, file());

  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
});
