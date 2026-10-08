import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  SourceStatus,
  sourceIndicator,
  summariseWorkspaceSync,
  syncSummary,
} from "@/components/sources/source-status";
import type { WorkspaceSource } from "@/lib/api-types";

const NOW = new Date("2026-10-08T12:00:00Z");

function source(over: Partial<WorkspaceSource> = {}): WorkspaceSource {
  return {
    repo: "openai/cortex",
    kind: "github",
    status: "SUCCESS",
    pull_requests: 8,
    issues: 3,
    total_items: 11,
    last_attempted_at: "2026-10-08T11:55:00Z",
    last_synced_at: "2026-10-08T11:55:00Z",
    last_error: null,
    last_synced_by: "11111111-0000-4000-8000-000000000001",
    last_synced_by_name: "Ashwath",
    ...over,
  };
}

describe("sync indicators (T-10.3)", () => {
  it("shows a green Connected indicator for a source that completed", () => {
    render(<SourceStatus source={source()} now={NOW} />);
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(sourceIndicator("SUCCESS").dotClass).toContain("emerald");
  });

  it("shows a red Needs attention indicator and the error for a failure", () => {
    render(
      <SourceStatus
        source={source({
          status: "FAILED",
          last_error: "Repository openai/cortex not found or not accessible",
        })}
        now={NOW}
      />,
    );

    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(
      screen.getByText("Repository openai/cortex not found or not accessible"),
    ).toBeInTheDocument();
    expect(sourceIndicator("FAILED").dotClass).toContain("red");
  });

  it("shows an in-progress indicator while an ingestion is running", () => {
    render(<SourceStatus source={source({ status: "PENDING", last_synced_at: null })} now={NOW} />);
    expect(screen.getByText("Syncing…")).toBeInTheDocument();
    expect(sourceIndicator("PENDING").dotClass).toContain("amber");
  });

  it("does not rely on colour alone", () => {
    const labels = (["SUCCESS", "FAILED", "PENDING"] as const).map(
      (status) => sourceIndicator(status).label,
    );
    expect(new Set(labels).size).toBe(3);
  });
});

describe("syncSummary", () => {
  it("names when and who", () => {
    expect(syncSummary(source(), NOW)).toBe("Synced 5 min ago by Ashwath");
  });

  it("drops the name when nobody is recorded", () => {
    expect(syncSummary(source({ last_synced_by_name: null }), NOW)).toBe(
      "Synced 5 min ago",
    );
  });

  it("keeps reporting the last success of a failing source", () => {
    const failing = source({
      status: "FAILED",
      last_error: "GitHub rate limit reached",
      last_synced_at: "2026-10-05T12:00:00Z",
      last_attempted_at: "2026-10-08T11:59:00Z",
    });

    // The failure and the age of the data are both true, and both shown: the
    // items on screen really are three days old.
    expect(syncSummary(failing, NOW)).toBe("Synced 3 days ago by Ashwath");
    render(<SourceStatus source={failing} now={NOW} />);
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("Synced 3 days ago by Ashwath")).toBeInTheDocument();
  });

  it("says so when a failing source never synced at all", () => {
    expect(
      syncSummary(source({ status: "FAILED", last_synced_at: null }), NOW),
    ).toBe("Never synced");
  });

  it("stays quiet about a repo ingested before sync state was recorded", () => {
    expect(
      syncSummary(
        source({ last_synced_at: null, last_attempted_at: null, last_synced_by_name: null }),
        NOW,
      ),
    ).toBeNull();
  });

  it("stays quiet about a first ingestion still in progress", () => {
    expect(syncSummary(source({ status: "PENDING", last_synced_at: null }), NOW)).toBeNull();
  });
});

describe("summariseWorkspaceSync", () => {
  it("has nothing to say about a workspace with no sources", () => {
    expect(summariseWorkspaceSync([])).toBeNull();
  });

  it("reports the newest success across every source", () => {
    const summary = summariseWorkspaceSync([
      source({ repo: "a", last_synced_at: "2026-10-01T12:00:00Z" }),
      source({ repo: "b", last_synced_at: "2026-10-08T11:55:00Z" }),
      source({ repo: "c", last_synced_at: null }),
    ]);

    // The graph on screen is as new as the newest thing written into it.
    expect(summary).toMatchObject({
      status: "SUCCESS",
      syncedAt: "2026-10-08T11:55:00Z",
      failing: 0,
      total: 3,
    });
  });

  it("lets one broken source outrank three healthy ones", () => {
    const summary = summariseWorkspaceSync([
      source({ repo: "a" }),
      source({ repo: "b" }),
      source({ repo: "c", status: "FAILED" }),
    ]);

    expect(summary).toMatchObject({ status: "FAILED", failing: 1, total: 3 });
    // Still reports freshness: the healthy sources' data is really on screen.
    expect(summary?.syncedAt).not.toBeNull();
  });

  it("lets an ingestion in flight outrank a failure", () => {
    const summary = summariseWorkspaceSync([
      source({ repo: "a", status: "FAILED" }),
      source({ repo: "b", status: "PENDING" }),
    ]);

    expect(summary?.status).toBe("PENDING");
    expect(summary?.failing).toBe(1);
  });

  it("ignores an unparseable timestamp rather than reporting it", () => {
    const summary = summariseWorkspaceSync([
      source({ repo: "a", last_synced_at: "not a date" }),
      source({ repo: "b", last_synced_at: "2026-10-08T11:55:00Z" }),
    ]);

    expect(summary?.syncedAt).toBe("2026-10-08T11:55:00Z");
  });

  it("reports no timestamp when nothing has ever synced", () => {
    const summary = summariseWorkspaceSync([
      source({ repo: "a", status: "FAILED", last_synced_at: null }),
    ]);

    expect(summary).toMatchObject({ status: "FAILED", syncedAt: null });
  });
});
