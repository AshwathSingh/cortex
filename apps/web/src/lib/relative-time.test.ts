import { describe, expect, it } from "vitest";

import { formatAbsoluteTime, formatRelativeTime } from "@/lib/relative-time";

const NOW = new Date("2026-10-08T12:00:00Z");

function ago(seconds: number): string {
  return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

describe("formatRelativeTime", () => {
  it("reads as the ticket's example", () => {
    expect(formatRelativeTime(ago(5 * 60), NOW)).toBe("5 min ago");
  });

  it("rounds down to the unit in use", () => {
    expect(formatRelativeTime(ago(30), NOW)).toBe("just now");
    expect(formatRelativeTime(ago(59), NOW)).toBe("just now");
    expect(formatRelativeTime(ago(60), NOW)).toBe("1 min ago");
    expect(formatRelativeTime(ago(59 * 60), NOW)).toBe("59 min ago");
    expect(formatRelativeTime(ago(60 * 60), NOW)).toBe("1 hour ago");
    expect(formatRelativeTime(ago(5 * 60 * 60), NOW)).toBe("5 hours ago");
    expect(formatRelativeTime(ago(24 * 60 * 60), NOW)).toBe("1 day ago");
    expect(formatRelativeTime(ago(3 * 24 * 60 * 60), NOW)).toBe("3 days ago");
    expect(formatRelativeTime(ago(14 * 24 * 60 * 60), NOW)).toBe("2 weeks ago");
    expect(formatRelativeTime(ago(60 * 24 * 60 * 60), NOW)).toBe("2 months ago");
    expect(formatRelativeTime(ago(400 * 24 * 60 * 60), NOW)).toBe("1 year ago");
  });

  it("treats a clock skewed into the future as just now", () => {
    expect(formatRelativeTime(new Date(NOW.getTime() + 30_000).toISOString(), NOW))
      .toBe("just now");
  });

  it("has nothing to say about a missing or unparseable timestamp", () => {
    expect(formatRelativeTime(null, NOW)).toBeNull();
    expect(formatRelativeTime(undefined, NOW)).toBeNull();
    expect(formatRelativeTime("", NOW)).toBeNull();
    expect(formatRelativeTime("not a date", NOW)).toBeNull();
  });
});

describe("formatAbsoluteTime", () => {
  it("renders a timestamp for the tooltip", () => {
    expect(formatAbsoluteTime("2026-10-08T12:00:00Z")).toContain("2026");
  });

  it("is undefined when there is no usable timestamp", () => {
    expect(formatAbsoluteTime(null)).toBeUndefined();
    expect(formatAbsoluteTime("not a date")).toBeUndefined();
  });
});
