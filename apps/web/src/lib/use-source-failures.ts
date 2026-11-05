"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiRequest } from "@/lib/api";
import type { SourceFailure } from "@/lib/api-types";

/**
 * T-12.2: the workspace's unresolved ingestion failures, kept fresh.
 *
 * Shared by the banner in the workspace shell and the list on the Sources page,
 * because they are two views of one fact and must never disagree about it.
 *
 * Polled rather than fetched once. A failure can appear while the reader is
 * sitting on an unrelated page -- somebody else's re-sync, or their own
 * synchronous ingestion finishing minutes after the request that started it --
 * and AC1 is about being told without going to look.
 *
 * A failed *poll* is deliberately silent. The banner exists to report broken
 * sources; replacing it with "could not check for broken sources" would be
 * noise on every page in the workspace for the duration of a hiccup. The page
 * the reader actually went to has its own error handling.
 */
const POLL_MS = 30_000;

export type SourceFailuresState = {
  failures: SourceFailure[];
  isLoading: boolean;
  /** Re-read now, after a retry or a sign-in. */
  refresh: () => void;
};

export function useSourceFailures(workspaceId: string): SourceFailuresState {
  const [failures, setFailures] = useState<SourceFailure[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => setVersion((current) => current + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setInterval> | null = null;

    async function load() {
      try {
        const next = await apiRequest<SourceFailure[]>(
          `/api/workspaces/${workspaceId}/source-failures`,
          { signal: controller.signal },
        );
        setFailures(next);
      } catch (requestError) {
        if (controller.signal.aborted) return;
        // 401 is left to the page the reader is on: this hook runs on every
        // workspace page and racing them all to redirect would be worse.
        if (requestError instanceof ApiError && requestError.status === 403) {
          setFailures([]);
        }
      } finally {
        if (!controller.signal.aborted) setIsLoading(false);
      }
    }

    void load();
    timer = setInterval(() => void load(), POLL_MS);
    return () => {
      controller.abort();
      if (timer) clearInterval(timer);
    };
  }, [version, workspaceId]);

  return { failures, isLoading, refresh };
}
