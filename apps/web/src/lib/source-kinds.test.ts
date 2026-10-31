import { describe, expect, it } from "vitest";

import type { WorkspaceSource } from "@/lib/api-types";
import { githubUrl, sourceKindMeta } from "@/lib/source-kinds";

function source(over: Partial<WorkspaceSource> = {}): WorkspaceSource {
  return {
    repo: "openai/cortex",
    kind: "github",
    status: "SUCCESS",
    pull_requests: 8,
    issues: 3,
    total_items: 11,
    sections: 0,
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

describe("upload", () => {
  const row = source({
    kind: "upload",
    repo: "prd.md",
    display_name: "prd.md",
    pull_requests: 0,
    issues: 0,
    sections: 4,
    total_items: 5,
  });

  it("is titled by its filename", () => {
    expect(sourceKindMeta("upload").title(row)).toBe("prd.md");
  });

  it("has nothing to link to, because the file was never stored", () => {
    expect(sourceKindMeta("upload").href(row)).toBeNull();
    expect(sourceKindMeta("upload").destination).toBeNull();
  });

  it("counts sections rather than pull requests", () => {
    expect(
      sourceKindMeta("upload").countColumns.map((column) => [
        column.label,
        column.value(row),
      ]),
    ).toEqual([
      ["Sections", 4],
      ["Indexed", 5],
    ]);
  });

  it("falls back to the reference rather than rendering an empty row", () => {
    expect(
      sourceKindMeta("upload").title({ ...row, display_name: null }),
    ).toBe("prd.md");
  });
});

describe("an unrecognised kind", () => {
  it("still renders, because the server may add one before the UI knows it", () => {
    const row = source({ kind: "slack", display_name: "Acme" });
    const meta = sourceKindMeta("slack");

    expect(meta.title(row)).toBe("Acme");
    expect(meta.href(row)).toBeNull();
    expect(meta.countColumns.map((column) => column.label)).toEqual(["Indexed"]);
  });
});
