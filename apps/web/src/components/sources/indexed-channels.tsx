"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { WorkspaceSource } from "@/lib/api-types";
import type { IndexedChannel, RemovalTarget } from "./remove-source-modal";

export function IndexedChannels({
  workspaceId,
  source,
  onRemove,
}: {
  workspaceId: string;
  source: WorkspaceSource;
  onRemove: (target: RemovalTarget, trigger: HTMLButtonElement) => void;
}) {
  const [channels, setChannels] = useState<IndexedChannel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({
      kind: source.kind,
      external_ref: source.repo,
    });
    void apiRequest<IndexedChannel[]>(
      `/api/workspaces/${workspaceId}/sources/channels?${query}`,
      { signal: controller.signal },
    )
      .then((rows) => {
        if (!controller.signal.aborted) setChannels(rows);
      })
      .catch((failure) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof ApiError
              ? failure.message
              : "Unable to load indexed channels.",
          );
      });
    return () => controller.abort();
  }, [workspaceId, source.kind, source.repo, version]);
  return (
    <div className="lg:col-span-2 rounded-xl border border-border/30 px-4 py-1">
      {error ? (
        <div className="pb-3">
          <FeedbackAlert message={error} />
          <Button
            type="button"
            size="small"
            className="mt-3"
            onClick={() => {
              setError(null);
              setVersion((v) => v + 1);
            }}
          >
            Try again
          </Button>
        </div>
      ) : channels === null ? (
        <p role="status" className="py-3 text-sm text-muted">
          Loading indexed channels…
        </p>
      ) : channels.length === 0 ? (
        <p className="py-3 text-sm text-muted">No indexed channels remain.</p>
      ) : (
        <ul className="divide-y divide-border/20">
          {channels.map((channel) => (
            <li
              key={channel.id}
              className="flex items-center justify-between gap-4 py-3"
            >
              <div className="min-w-0">
                <p className="break-words text-sm text-foreground">
                  #{channel.name}
                </p>
                <p className="mt-1 text-xs text-muted">
                  {channel.messages.toLocaleString()} indexed messages
                </p>
                {channel.removal_pending ? (
                  <p role="status" className="text-xs text-muted">
                    Removal incomplete. Retry this channel to finish cleanup.
                  </p>
                ) : null}
              </div>
              <Button
                type="button"
                size="small"
                variant="ghost"
                aria-label={`${channel.removal_pending ? "Retry removal of" : "Remove"} #${channel.name}`}
                onClick={(event) =>
                  onRemove({ source, channel }, event.currentTarget)
                }
              >
                {channel.removal_pending ? "Retry removal" : "Remove"}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
