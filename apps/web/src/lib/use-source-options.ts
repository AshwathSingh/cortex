"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, apiRequest } from "@/lib/api";
import type { SourceOptions } from "@/lib/api-types";

type State =
  | { kind: "loading" }
  | { kind: "ready"; workspaceId: string; data: SourceOptions }
  | { kind: "error"; workspaceId: string; message: string };

export function useSourceOptions(workspaceId: string) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    void apiRequest<SourceOptions>(
      `/api/workspaces/${workspaceId}/sources/options`,
      { signal: controller.signal },
    )
      .then((data) => {
        if (
          typeof data.can_manage_sources !== "boolean" ||
          !Array.isArray(data.providers)
        )
          throw new Error("Invalid source availability response");
        if (!controller.signal.aborted)
          setState({ kind: "ready", workspaceId, data });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) {
          router.replace("/login");
          return;
        }
        setState({
          kind: "error",
          workspaceId,
          message:
            error instanceof ApiError
              ? error.message
              : "Unable to check source availability. Try again.",
        });
      });
    return () => controller.abort();
  }, [router, workspaceId, version]);
  const currentState: State =
    state.kind !== "loading" && state.workspaceId !== workspaceId
      ? { kind: "loading" }
      : state;
  return { state: currentState, refresh };
}
