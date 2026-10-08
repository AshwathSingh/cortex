import type { SourceSyncStatus, WorkspaceSource } from "@/lib/api-types";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/relative-time";

type Indicator = {
  label: string;
  /** Tailwind classes for the dot and the label, by severity. */
  dotClass: string;
  textClass: string;
};

/**
 * T-10.2: what each sync status looks like on the Sources page.
 *
 * "Connected" rather than US-42's "Indexed": the row already has an "Indexed"
 * column for the item count, and two identical words in one row read as a
 * mistake. These three labels are connection health. The state is carried by a
 * dot *and* a label, so it is never colour alone.
 */
const INDICATORS: Record<SourceSyncStatus, Indicator> = {
  SUCCESS: {
    label: "Connected",
    dotClass: "bg-emerald-400",
    textClass: "text-muted",
  },
  FAILED: {
    label: "Needs attention",
    dotClass: "bg-red-400",
    textClass: "text-red-300",
  },
  PENDING: {
    label: "Syncing…",
    dotClass: "bg-amber-400",
    textClass: "text-amber-200",
  },
};

export function sourceIndicator(status: SourceSyncStatus): Indicator {
  return INDICATORS[status] ?? INDICATORS.SUCCESS;
}

/**
 * How old this source's data is, or null when there is nothing honest to say.
 *
 * A failed source keeps reporting its last successful sync: the items on screen
 * really are that old, and hiding it would make a stale graph look current. A
 * repository ingested before sync state was recorded has no timestamp at all,
 * and inventing one would be worse than omitting it.
 */
export function syncSummary(
  source: WorkspaceSource,
  now: Date = new Date(),
): string | null {
  const synced = formatRelativeTime(source.last_synced_at, now);
  if (synced) {
    return source.last_synced_by_name
      ? `Synced ${synced} by ${source.last_synced_by_name}`
      : `Synced ${synced}`;
  }
  return source.status === "FAILED" ? "Never synced" : null;
}

export function SourceStatus({
  source,
  now,
}: {
  source: WorkspaceSource;
  now?: Date;
}) {
  const { label, dotClass, textClass } = sourceIndicator(source.status);
  const summary = syncSummary(source, now);

  return (
    <div className="mt-1">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <span aria-hidden="true" className={`size-1.5 rounded-full ${dotClass}`} />
        <span className={textClass}>{label}</span>
        {summary ? (
          <>
            <span aria-hidden="true" className="text-subtle">
              ·
            </span>
            <span
              className="text-muted"
              title={formatAbsoluteTime(source.last_synced_at)}
            >
              {summary}
            </span>
          </>
        ) : null}
      </p>
      {source.status === "FAILED" && source.last_error ? (
        <p className="mt-1.5 max-w-prose text-xs leading-5 text-red-300/80">
          {source.last_error}
        </p>
      ) : null}
    </div>
  );
}
