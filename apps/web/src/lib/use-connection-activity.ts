"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { ConnectionSummary } from "@/lib/api-types";

/** How often to look again while the Connection Agent is still working. */
export const ACTIVITY_POLL_MS = 5_000;

/**
 * How many extra polls to run after a trigger (an ingestion or a manual
 * refresh) even once a read reports nothing in flight. The agent job is
 * queued on a background thread pool (see `events.emit_artifact_ingested`),
 * so the very first read after ingestion can land before that thread has
 * marked anything "running" -- without this grace window, that one early,
 * unlucky read would permanently stop polling and the resulting edges would
 * never appear without a manual page reload.
 */
export const ACTIVITY_GRACE_POLLS = 3;

/** True while artifacts are queued or being analysed, i.e. new edges may still arrive. */
export function isAnalysing(summary: ConnectionSummary | null): boolean {
  return Boolean(summary && ((summary.analysis?.running ?? 0) + (summary.analysis?.pending ?? 0)) > 0);
}

/**
 * US-23: the Connection Agent's progress, for live edges without a reload.
 *
 * Polls only while analysis is in flight or might be about to start
 * (otherwise one read per load), and bumps `tick` whenever the counts change
 * so the graph view refetches. Each poll decides whether to schedule the next
 * one from its own fresh result, rather than from a stale `analysing` value
 * captured before that result came back -- so the decision is never a step
 * behind what the server just reported. Polling rather than a socket because
 * the app has no realtime channel. A failed read is silent: the graph itself
 * is the source of truth and stays as it was.
 */
export function useConnectionActivity(workspaceId: string, reloadToken = 0) {
  const [summary, setSummary] = useState<ConnectionSummary | null>(null);
  const [tick, setTick] = useState(0);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    let graceRemaining = ACTIVITY_GRACE_POLLS;

    async function poll() {
      let keepGoing = graceRemaining > 0;
      try {
        const next = await apiRequest<ConnectionSummary>(
          `/api/workspaces/${workspaceId}/connections/summary`,
          { signal: controller.signal },
        );
        setSummary((previous) => {
          if (previous && JSON.stringify(previous) !== JSON.stringify(next)) {
            setTick((t) => t + 1);
          }
          return previous && JSON.stringify(previous) === JSON.stringify(next) ? previous : next;
        });
        keepGoing = isAnalysing(next) || graceRemaining > 0;
      } catch {
        // Deliberately silent; see the note above.
      } finally {
        graceRemaining -= 1;
        if (!controller.signal.aborted && keepGoing) {
          timer = window.setTimeout(poll, ACTIVITY_POLL_MS);
        }
      }
    }

    void poll();
    return () => {
      controller.abort();
      if (timer) window.clearTimeout(timer);
    };
  }, [workspaceId, reloadToken, version]);

  return { summary, tick, refresh };
}
