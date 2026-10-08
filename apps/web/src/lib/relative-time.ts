/**
 * T-10.2: "Synced 5 min ago" — how old a source's data is, in words.
 *
 * Hand-rolled rather than `Intl.RelativeTimeFormat` so the wording matches the
 * copy in the ticket ("5 min ago", not "5 minutes ago") and so the thresholds
 * are explicit. `now` is a parameter so the result is testable and so a caller
 * can format a whole list against one instant.
 *
 * Only ever rendered after a client-side fetch, so there is no server/client
 * hydration mismatch to worry about.
 */

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

/** A relative age, or null when the timestamp is missing or unparseable. */
export function formatRelativeTime(
  timestamp: string | null | undefined,
  now: Date = new Date(),
): string | null {
  if (!timestamp) return null;
  const then = new Date(timestamp);
  const thenMs = then.getTime();
  if (Number.isNaN(thenMs)) return null;

  // A clock skewed a few seconds ahead of the server is normal; reporting a
  // sync in the future is not.
  const seconds = Math.max(0, Math.floor((now.getTime() - thenMs) / 1000));

  if (seconds < MINUTE) return "just now";
  if (seconds < HOUR) return `${Math.floor(seconds / MINUTE)} min ago`;
  if (seconds < DAY) return plural(Math.floor(seconds / HOUR), "hour");
  if (seconds < WEEK) return plural(Math.floor(seconds / DAY), "day");
  if (seconds < MONTH) return plural(Math.floor(seconds / WEEK), "week");
  if (seconds < YEAR) return plural(Math.floor(seconds / MONTH), "month");
  return plural(Math.floor(seconds / YEAR), "year");
}

/** The full timestamp, for a `title` tooltip beside the relative one. */
export function formatAbsoluteTime(
  timestamp: string | null | undefined,
): string | undefined {
  if (!timestamp) return undefined;
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toLocaleString();
}
