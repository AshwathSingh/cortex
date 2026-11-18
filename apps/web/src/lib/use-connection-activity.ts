"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { ConnectionSummary } from "@/lib/api-types";

/** How often to look again while the Connection Agent is still working. */
export const ACTIVITY_POLL_MS = 5_000;

/** True while artifacts are queued or being analysed, i.e. new edges may still arrive. */
export function isAnalysing(summary: ConnectionSummary | null): boolean {
  return Boolean(summary && ((summary.analysis?.running ?? 0) + (summary.analysis?.pending ?? 0)) > 0);
}

/**
 * US-23: the Connection Agent's progress, for live edges without a reload.
 *
 * Polls only while analysis is in flight (otherwise one read per load), and
 * bumps `tick` whenever the counts change so the graph view refetches. Polling
 * rather than a socket because the app has no realtime channel. A failed read is
 * silent: the graph itself is the source of truth and stays as it was.
 */
export function useConnectionActivity(workspaceId: string, reloadToken = 0) {
  const [summary, setSummary] = useState<ConnectionSummary | null>(null);
  const [tick, setTick] = useState(0);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  const analysing = isAnalysing(summary);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
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
      } catch {
        // Deliberately silent; see the note above.
      }
    }
    void load();
    const timer = analysing ? window.setInterval(() => void load(), ACTIVITY_POLL_MS) : undefined;
    return () => {
      controller.abort();
      if (timer) window.clearInterval(timer);
    };
  }, [workspaceId, reloadToken, version, analysing]);

  return { summary, tick, refresh };
}
