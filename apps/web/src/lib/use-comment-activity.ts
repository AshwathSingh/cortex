"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { CommentActivity } from "@/lib/api-types";

/**
 * T-27.4: which targets carry comments, and which of them this reader has not
 * seen.
 *
 * One request for the whole canvas, not one per node: the badges have to be
 * drawn before the reader clicks anything (AC2), and a workspace can hold
 * thousands of nodes.
 *
 * A failed read is silent and leaves the badges as they were. Losing a badge is
 * a missing hint; an error banner over the graph because a secondary request
 * failed would be worse than the hint being a few seconds stale.
 */
export function useCommentActivity(workspaceId: string) {
  const [activity, setActivity] = useState<CommentActivity[]>([]);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => setVersion((current) => current + 1), []);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        const next = await apiRequest<CommentActivity[]>(
          `/api/workspaces/${workspaceId}/graph/comments/activity`,
          { signal: controller.signal },
        );
        setActivity(next);
      } catch {
        // Deliberately silent; see the note above.
      }
    }

    void load();
    return () => controller.abort();
  }, [version, workspaceId]);

  return { activity, refresh };
}
