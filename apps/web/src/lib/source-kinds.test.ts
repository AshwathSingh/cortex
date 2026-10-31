import { describe, expect, it } from "vitest";

import type { WorkspaceSource } from "@/lib/api-types";
import { githubUrl, isChatKind, sourceKindMeta } from "@/lib/source-kinds";

function source(over: Partial<WorkspaceSource> = {}): WorkspaceSource {
  return {
    repo: "openai/cortex",
    kind: "github",
    status: "SUCCESS",
    pull_requests: 8,
    issues: 3,
    total_items: 11,
    channels: 0,
    messages: 0,
    display_name: null,
    last_attempted_at: null,
    last_synced_at: null,
    last_error: null,
    last_synced_by: null,
    last_synced_by_name: null,
    ...over,
  };
}

describe("github", () => {
  it("is titled and linked by its repository path", () => {
    const meta = sourceKindMeta("github");
    const row = source();

    expect(meta.title(row)).toBe("openai/cortex");
    expect(meta.href(row)).toBe("https://github.com/openai/cortex");
    expect(meta.destination).toBe("GitHub");
  });

  it("counts pull requests and issues", () => {
    const row = source();

    expect(
      sourceKindMeta("github").countColumns.map((column) => [
        column.label,
        column.value(row),
      ]),
    ).toEqual([
      ["Pull requests", 8],
      ["Issues", 3],
      ["Indexed", 11],
    ]);
  });

  it("escapes each path segment separately", () => {
    // Encoding the whole string would turn the separating slash into %2F.
    expect(githubUrl("a b/c d")).toBe("https://github.com/a%20b/c%20d");
  });
});

describe("slack", () => {
  const row = source({
    kind: "slack",
    repo: "T0ACME",
    display_name: "Acme",
    channels: 2,
    messages: 30,
    total_items: 32,
    pull_requests: 0,
    issues: 0,
  });

  it("is titled by the team name, never the opaque team id", () => {
    expect(sourceKindMeta("slack").title(row)).toBe("Acme");
  });

  it("has no external link, because Slack's needs the team subdomain", () => {
    expect(sourceKindMeta("slack").href(row)).toBeNull();
    expect(sourceKindMeta("slack").destination).toBeNull();
  });

  it("falls back to the team id rather than rendering an empty row", () => {
    expect(
      sourceKindMeta("slack").title({ ...row, display_name: null }),
    ).toBe("T0ACME");
  });

  it("counts channels and messages", () => {
    expect(
      sourceKindMeta("slack").countColumns.map((column) => [
        column.label,
        column.value(row),
      ]),
    ).toEqual([
      ["Channels", 2],
      ["Messages", 30],
      ["Indexed", 32],
    ]);
  });
});

describe("discord", () => {
  const row = source({
    kind: "discord",
    repo: "912340000000000000",
    display_name: "Acme Guild",
    channels: 1,
    messages: 7,
    total_items: 8,
  });

  it("links to the guild", () => {
    expect(sourceKindMeta("discord").href(row)).toBe(
      "https://discord.com/channels/912340000000000000",
    );
  });

  it("is titled by the server name", () => {
    expect(sourceKindMeta("discord").title(row)).toBe("Acme Guild");
  });
});

describe("an unrecognised kind", () => {
  it("still renders, because the server may add one before the UI knows it", () => {
    const row = source({ kind: "notion", display_name: "Specs" });
    const meta = sourceKindMeta("notion");

    expect(meta.title(row)).toBe("Specs");
    expect(meta.href(row)).toBeNull();
    expect(meta.countColumns.map((column) => column.label)).toEqual(["Indexed"]);
  });
});

describe("isChatKind", () => {
  it("accepts only the two providers connected by authorisation", () => {
    expect(isChatKind("slack")).toBe(true);
    expect(isChatKind("discord")).toBe(true);
    expect(isChatKind("github")).toBe(false);
  });
});
