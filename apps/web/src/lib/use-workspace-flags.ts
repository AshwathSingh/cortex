"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiRequest } from "@/lib/api";
import type { WorkspaceFlags } from "@/lib/api-types";

/**
 * T-28.2: the Pruning Agent's findings for a workspace.
 *
 * Fetched on mount and on demand, never polled. The rules run on the read, so
 * every fetch is a fresh run over the whole workspace -- cheap enough to ask for
 * when the reader wants it, too heavy to repeat on a timer behind their back.
 */

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: WorkspaceFlags }
  //: `status` is carried so the caller can act on 401 without matching on the
  //: message text, which is the server's wording and not a contract.
  | { kind: "error"; message: string; status: number | null };

export function useWorkspaceFlags(workspaceId: string) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [version, setVersion] = useState(0);

  const refresh = useCallback(() => setVersion((current) => current + 1), []);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        const data = await apiRequest<WorkspaceFlags>(
          `/api/workspaces/${workspaceId}/flags`,
          { signal: controller.signal },
        );
        setState({ kind: "ready", data });
      } catch (requestError) {
        if (controller.signal.aborted) return;
        setState({
          kind: "error",
          message:
            requestError instanceof ApiError
              ? requestError.message
              : "Unable to check this workspace for review items.",
          status: requestError instanceof ApiError ? requestError.status : null,
        });
      }
    }

    void load();
    return () => controller.abort();
  }, [version, workspaceId]);

  return { state, refresh, isChecking: state.kind === "loading" };
}
