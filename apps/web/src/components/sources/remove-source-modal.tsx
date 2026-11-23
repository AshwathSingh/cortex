"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { WorkspaceSource } from "@/lib/api-types";
import { isChatKind, sourceKindMeta } from "@/lib/source-kinds";

export type IndexedChannel = { id: string; name: string; messages: number };
export type RemovalTarget = {
  source: WorkspaceSource;
  channel?: IndexedChannel;
};

export function RemoveSourceModal({
  workspaceId,
  target,
  onClose,
  onRemoved,
}: {
  workspaceId: string;
  target: RemovalTarget;
  onClose: () => void;
  onRemoved: (title: string) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const submitting = useRef(false);
  const router = useRouter();
  const [isRemoving, setIsRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const { source, channel } = target;
  const meta = sourceKindMeta(source.kind);
  const title = channel ? `#${channel.name}` : meta.title(source);
  const chat = isChatKind(source.kind);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog?.open) dialog?.showModal();
    cancelRef.current?.focus();
    return () => dialog?.close();
  }, []);

  function close() {
    if (submitting.current) return;
    dialogRef.current?.close();
    onClose();
  }

  async function remove(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || forbidden || needsSignIn) return;
    submitting.current = true;
    setIsRemoving(true);
    setError(null);
    try {
      await apiRequest(`/api/workspaces/${workspaceId}/sources`, {
        method: "DELETE",
        body: JSON.stringify({
          kind: source.kind,
          external_ref: source.repo,
          channel_id: channel?.id ?? null,
        }),
      });
      onRemoved(title);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) {
        setNeedsSignIn(true);
        setError(
          "Your session has expired. Sign in again to remove this source.",
        );
      } else if (failure instanceof ApiError && failure.status === 403) {
        setForbidden(true);
        setError(
          "You no longer have permission to manage sources in this workspace.",
        );
      } else {
        setError(
          failure instanceof ApiError
            ? failure.message
            : "Removal could not finish. Check your connection and try again. Retrying safely completes any remaining cleanup.",
        );
      }
      submitting.current = false;
      setIsRemoving(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="remove-source-title"
      aria-describedby="remove-source-description"
      aria-modal="true"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(32rem,calc(100%-2rem))] overflow-hidden rounded-2xl border border-border/40 bg-surface p-0 text-foreground shadow-[0_28px_80px_rgb(0_0_0/0.55)] backdrop:bg-background/85 backdrop:backdrop-blur-[2px]"
    >
      <form
        onSubmit={(event) => void remove(event)}
        aria-busy={isRemoving}
        className="flex max-h-[calc(100dvh-2rem)] flex-col"
      >
        <div className="shrink-0 border-b border-border/30 px-6 py-5">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-subtle">
            Workspace sources
          </p>
          <h2
            id="remove-source-title"
            className="mt-2 text-xl font-semibold tracking-tight"
          >
            {channel ? "Remove channel?" : "Remove source?"}
          </h2>
          <p
            id="remove-source-description"
            className="mt-2 text-sm leading-6 text-muted"
          >
            Remove this {channel ? "channel" : meta.noun} and its indexed
            content from this workspace. This cannot be undone.
          </p>
        </div>
        <div className="min-h-0 space-y-5 overflow-y-auto px-6 py-5">
          <div className="rounded-xl border border-border/30 bg-surface-raised/50 px-4 py-3">
            <p className="break-words text-sm font-semibold text-foreground [overflow-wrap:anywhere]">
              {title}
            </p>
            <p className="mt-1 text-xs leading-5 text-muted">
              {channel
                ? `${meta.title(source)} · ${channel.messages.toLocaleString()} indexed messages`
                : `${meta.noun[0].toUpperCase()}${meta.noun.slice(1)} · ${source.total_items.toLocaleString()} indexed items`}
            </p>
          </div>
          <div className="text-sm leading-6 text-muted">
            <p className="font-medium text-foreground">What will be removed</p>
            <p className="mt-1">
              {source.kind === "github"
                ? "Indexed pull requests and issues"
                : source.kind === "upload"
                  ? "The indexed document and its sections"
                  : channel
                    ? "This channel and its indexed messages"
                    : "All indexed channels and messages from this source"}
              , along with their graph relationships, attached comments and
              review evidence.
            </p>
            <p className="mt-3">
              Content from other sources and shared people will be kept.{" "}
              {source.kind === "upload"
                ? "Your original file is unaffected. You can upload it again later."
                : "The original content on the provider is unaffected."}
            </p>
            {chat ? (
              <p className="mt-3">
                Your {source.kind === "slack" ? "Slack" : "Discord"} connection
                stays active.{" "}
                {channel ? "Other indexed channels stay available. " : ""}You
                can choose channels to ingest again later. Disconnect the
                provider separately to revoke access.
              </p>
            ) : null}
          </div>
          <FeedbackAlert message={error} />
          {isRemoving ? (
            <p role="status" className="text-sm text-muted">
              Removing indexed content and cleaning up references…
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-border/30 px-6 py-4">
          <Button
            ref={cancelRef}
            type="button"
            variant="ghost"
            disabled={isRemoving}
            onClick={close}
          >
            Cancel
          </Button>
          {needsSignIn ? (
            <Button
              type="button"
              variant="primary"
              onClick={() => router.replace("/login")}
            >
              Sign in again
            </Button>
          ) : (
            <Button
              type="submit"
              variant="danger"
              disabled={isRemoving || forbidden}
            >
              {isRemoving
                ? "Removing…"
                : channel
                  ? "Remove channel"
                  : "Remove source"}
            </Button>
          )}
        </div>
      </form>
    </dialog>
  );
}
