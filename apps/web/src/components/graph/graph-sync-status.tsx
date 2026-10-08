"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  sourceIndicator,
  summariseWorkspaceSync,
} from "@/components/sources/source-status";
import { Button } from "@/components/ui/button";
import { useWorkspace } from "@/components/workspaces/workspace-context";
import { ApiError, apiRequest } from "@/lib/api";
import type { IngestResult, WorkspaceSource } from "@/lib/api-types";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/relative-time";
import { canManageSources } from "@/lib/workspace-permissions";

/** Matches the Sources page: a source mid-ingestion settles within seconds. */
const SYNC_POLL_MS = 5_000;

/**
 * A ceiling on how long one in-flight ingestion is polled for, so a row the
 * server never clears cannot leave a timer running forever. Reaching it stops
 * the polling and nothing else: whether that ingestion is alive is the server's
 * question, not ours, and it answers it by holding or releasing the lease that
 * `POST /api/ingest/github` takes.
 */
export const MAX_SYNC_POLLS = 120;

/**
 * Failures that belong to one repository. Everything else -- 403, 409, 429,
 * 503 -- is about the workspace, the account or the server, so the sources
 * after it would fail the same way; carrying on would just re-spend a rate
 * limit or hammer a database that is already down.
 */
const SOURCE_SPECIFIC_STATUSES = new Set([404, 422]);

function githubUrl(repo: string) {
  return `https://github.com/${repo.split("/").map(encodeURIComponent).join("/")}`;
}

/**
 * How fresh the graph is, and a way to refresh it, in the Graph page header.
 *
 * The canvas renders whatever the last ingestion wrote, with nothing on screen
 * to say when that was -- so a stale graph and a current one look identical.
 * This is the same `data_sources` state the Sources page shows, rolled up to
 * the workspace, because the graph is the union of every source.
 *
 * Renders nothing when the workspace has no sources: the canvas already has an
 * empty state, and a second prompt beside it would just be noise.
 */
export function GraphSyncStatus({
  workspaceId,
  onGraphChanged,
}: {
  workspaceId: string;
  /** Called when an ingestion lands new data, so the canvas can reload. */
  onGraphChanged?: () => void;
}) {
  const router = useRouter();
  const { workspace } = useWorkspace();
  const [sources, setSources] = useState<WorkspaceSource[] | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [isResyncing, setIsResyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resyncControllerRef = useRef<AbortController | null>(null);
  const graphChangedRef = useRef(onGraphChanged);
  const lastSyncedRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    graphChangedRef.current = onGraphChanged;
  }, [onGraphChanged]);

  useEffect(() => () => resyncControllerRef.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        const payload = await apiRequest<WorkspaceSource[]>(
          `/api/workspaces/${workspaceId}/sources`,
          { signal: controller.signal },
        );
        // Guarded, not trusted: the canvas is the page, and a header that
        // throws on an unexpected body would take the whole graph down.
        setSources(Array.isArray(payload) ? payload : []);
      } catch (requestError) {
        if (controller.signal.aborted) return;
        if (requestError instanceof ApiError && requestError.status === 401) {
          router.replace("/login");
          return;
        }
        // The graph itself is the page; a sources read that fails should leave
        // the header blank rather than take the canvas down with it.
        setSources(null);
      }
    }

    void load();
    return () => controller.abort();
  }, [requestVersion, router, workspaceId]);

  const summary = summariseWorkspaceSync(sources ?? []);
  const syncedAt = summary?.syncedAt ?? null;

  const isSyncing = isResyncing || summary?.status === "PENDING";

  useEffect(() => {
    if (!isSyncing) return;
    // Bounded in the closure, so it resets whenever an ingestion starts.
    let remaining = MAX_SYNC_POLLS;
    const timer = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) clearInterval(timer);
      setRequestVersion((version) => version + 1);
    }, SYNC_POLL_MS);
    return () => clearInterval(timer);
  }, [isSyncing]);

  // A newer sync anywhere in the workspace means the graph gained data, so the
  // canvas has to reload -- whether this tab triggered it or somebody else did.
  useEffect(() => {
    if (sources === null) return;
    const previous = lastSyncedRef.current;
    lastSyncedRef.current = syncedAt;
    if (previous === undefined || previous === syncedAt) return;
    graphChangedRef.current?.();
  }, [sources, syncedAt]);

  /**
   * Re-ingest every connected source, one at a time. The graph is the union of
   * all of them, so refreshing it means refreshing all of them; serially,
   * because they share the workspace's GitHub rate limit.
   */
  async function resyncAll() {
    if (!sources || sources.length === 0) return;
    const controller = new AbortController();
    resyncControllerRef.current = controller;
    setError(null);
    setIsResyncing(true);

    const failed: string[] = [];
    try {
      for (const source of sources) {
        try {
          await apiRequest<IngestResult>("/api/ingest/github", {
            method: "POST",
            body: JSON.stringify({
              repo_url: githubUrl(source.repo),
              workspace_id: workspaceId,
            }),
            signal: controller.signal,
          });
        } catch (requestError) {
          if (controller.signal.aborted) return;
          if (requestError instanceof ApiError && requestError.status === 401) {
            router.replace("/login");
            return;
          }
          if (!(requestError instanceof ApiError)) {
            // The server is unreachable, so every remaining source would fail
            // identically.
            setError("Could not reach the Cortex server.");
            return;
          }
          if (!SOURCE_SPECIFIC_STATUSES.has(requestError.status)) {
            // Workspace-wide: permission, a rate limit, another ingestion
            // already holding the lease, or the graph database being down.
            setError(requestError.message);
            return;
          }
          // Only a repository's own problem lets the run continue -- one broken
          // repo must not strand the ones after it.
          failed.push(source.repo);
        }
      }
      if (failed.length > 0) {
        // Each source recorded its own reason; the Sources page spells them out.
        setError(`Could not re-sync ${failed.join(", ")}.`);
      }
    } finally {
      if (!controller.signal.aborted) {
        setIsResyncing(false);
        setRequestVersion((version) => version + 1);
      }
      if (resyncControllerRef.current === controller) {
        resyncControllerRef.current = null;
      }
    }
  }

  if (!summary) return null;

  const status = isResyncing ? "PENDING" : summary.status;
  const { label, dotClass, textClass } = sourceIndicator(status);
  const synced = formatRelativeTime(summary.syncedAt);
  const runningFor = status === "PENDING" ? formatRelativeTime(summary.pendingSince) : null;
  const statusLabel =
    status === "FAILED" && summary.failing > 0
      ? `${label} · ${summary.failing} of ${summary.total} sources`
      : runningFor
        ? `${label} started ${runningFor}`
        : label;

  return (
    <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
      <p className="flex items-center gap-2 text-xs">
        <span aria-hidden="true" className={`size-1.5 rounded-full ${dotClass}`} />
        <span className={textClass}>{statusLabel}</span>
        {synced ? (
          <>
            <span aria-hidden="true" className="text-subtle">
              ·
            </span>
            <span className="text-muted" title={formatAbsoluteTime(summary.syncedAt)}>
              Synced {synced}
            </span>
          </>
        ) : null}
      </p>

      {canManageSources(workspace?.role) ? (
        <Button
          type="button"
          size="small"
          variant="muted"
          aria-label="Re-sync all sources"
          onClick={() => void resyncAll()}
          disabled={isResyncing}
        >
          Re-sync
        </Button>
      ) : null}

      {error ? (
        <p role="alert" className="w-full text-right text-xs text-red-300">
          {error}
        </p>
      ) : null}
    </div>
  );
}
