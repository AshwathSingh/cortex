"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiRequest } from "@/lib/api";
import type { ConnectionSuggestion } from "@/lib/api-types";

function label(value: string): string {
  return value.replaceAll("_", " ").toLowerCase();
}

/**
 * US-23: the review queue for relationships the Connection Agent was not sure
 * enough to add. Anyone in the workspace can read it; only editors get the
 * Approve/Reject buttons (the server enforces the same rule with a 403).
 */
export function SuggestedConnections({
  workspaceId,
  canEdit,
  version,
  onChanged,
  onClose,
}: {
  workspaceId: string;
  canEdit: boolean;
  /** Change it to refetch (e.g. when the agent finished more work). */
  version: number;
  /** Called after an approval/rejection so the graph and badge refresh. */
  onChanged: () => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<ConnectionSuggestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    apiRequest<ConnectionSuggestion[]>(
      `/api/workspaces/${workspaceId}/connections/suggestions`,
      { signal: controller.signal },
    )
      .then((next) => { setItems(next); setError(null); })
      .catch(() => { if (!controller.signal.aborted) setError("Unable to load suggested connections."); });
    return () => controller.abort();
  }, [workspaceId, version]);

  const review = useCallback(async (id: string, action: "approve" | "reject") => {
    setBusy(id);
    try {
      await apiRequest(`/api/workspaces/${workspaceId}/connections/suggestions/${id}/${action}`, { method: "POST" });
      setItems((current) => current?.filter((item) => item.id !== id) ?? current);
      setError(null);
      onChanged();
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 403
        ? "Only editors can review suggestions."
        : `Could not ${action} this suggestion. Please try again.`);
    } finally {
      setBusy(null);
    }
  }, [workspaceId, onChanged]);

  return (
    <aside aria-label="Suggested connections" className="rounded-panel border border-border/60 bg-surface/70 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Suggested connections</h2>
          <p className="mt-1 text-xs text-muted">Found by the Connection Agent, not yet in the graph.</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close suggested connections"
          className="inline-flex size-9 shrink-0 items-center justify-center rounded-control border border-border/60 text-muted hover:bg-surface hover:text-foreground">
          <span aria-hidden="true">×</span>
        </button>
      </div>
      {error ? <p role="alert" className="mt-4 text-sm text-danger">{error}</p> : null}
      {items === null && !error ? <p role="status" className="mt-4 text-sm text-muted">Loading…</p> : null}
      {items?.length === 0 ? <p className="mt-4 text-sm text-muted">No connections are waiting for review.</p> : null}
      <ul className="mt-4 space-y-4">
        {items?.map((item) => (
          <li key={item.id} className="rounded-lg border border-border/50 p-3 text-sm">
            <p className="font-medium text-foreground">{item.source.title}</p>
            <p className="my-1 text-xs text-muted">
              {label(item.relationship_type)} · {Math.round(item.confidence * 100)}% confidence
            </p>
            <p className="font-medium text-foreground">{item.target.title}</p>
            {item.evidence ? <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-5 text-muted">{item.evidence}</p> : null}
            {canEdit ? (
              <div className="mt-3 flex gap-2">
                <button type="button" disabled={busy === item.id} onClick={() => void review(item.id, "approve")}
                  className="rounded-lg border border-accent-bright/40 px-3 py-1.5 text-xs font-medium text-accent-bright hover:bg-accent/10 disabled:opacity-50">
                  Approve
                </button>
                <button type="button" disabled={busy === item.id} onClick={() => void review(item.id, "reject")}
                  className="rounded-lg border border-danger/40 px-3 py-1.5 text-xs font-medium text-danger hover:bg-danger/10 disabled:opacity-50">
                  Reject
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </aside>
  );
}
