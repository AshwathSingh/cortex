import { afterEach, describe, expect, it, vi } from "vitest";

import { askAssistant } from "@/lib/assistant-client";

function jsonResponse(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("askAssistant", () => {
  it("posts bounded history and validates structured citations", async () => {
    const fetchMock = vi.fn(
      (input: RequestInfo | URL, init?: RequestInit) => {
        void input;
        void init;
        return jsonResponse({
          answer: "Grounded answer",
          citations: [
            {
              id: "graph-1",
              kind: "graph",
              label: "Graph explorer",
              description: "Inspect the graph",
            },
          ],
        });
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;
    const history = Array.from({ length: 24 }, (_, index) => ({
      role: index % 2 === 0 ? ("user" as const) : ("assistant" as const),
      content: `message-${index}`,
    }));

    const response = await askAssistant({
      workspaceId: "workspace-1",
      question: "Why Neo4j?",
      history,
      signal,
    });

    expect(response.answer).toBe("Grounded answer");
    expect(response.citations[0].kind).toBe("graph");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/workspaces/workspace-1/assistant/query",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        signal,
      }),
    );
    const request = fetchMock.mock.calls[0][1];
    if (!request) throw new Error("Expected request options.");
    const body = JSON.parse(String(request.body));
    expect(body.history).toHaveLength(20);
    expect(body.history[0].content).toBe("message-4");
  });

  it("rejects citation kinds outside the trusted route allowlist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        jsonResponse({
          answer: "Unsafe answer",
          citations: [
            {
              id: "external",
              kind: "https://example.com",
              label: "External",
              description: "Untrusted destination",
            },
          ],
        }),
      ),
    );

    await expect(
      askAssistant({
        workspaceId: "workspace-1",
        question: "Open this link",
        history: [],
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow("Invalid assistant citation");
  });
});
