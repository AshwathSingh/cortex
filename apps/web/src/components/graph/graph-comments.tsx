"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { GraphComment } from "@/lib/api-types";
import type { CommentTargetRef } from "@/lib/graph-comment-target";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/relative-time";

/**
 * T-27.3: the discussion on the selected node or edge.
 *
 * Oldest first, because it is an argument rather than a feed -- AC1 says so and
 * it is the only order the thread reads correctly in.
 *
 * Opening a thread marks it seen (T-27.4). That happens here rather than in the
 * canvas because this component is the only thing that knows the comments were
 * actually put in front of the reader.
 *
 * The composer is a plain form: Enter inserts a newline and the button submits.
 * A comment is often a paragraph with a line break in it, and losing one to an
 * over-eager Enter-to-send is worse than one extra click.
 */

const MAX_LENGTH = 4000;

type State =
  | { kind: "loading" }
  | { kind: "ready"; comments: GraphComment[] }
  | { kind: "error"; message: string };

function authorLabel(comment: GraphComment) {
  // A comment outlives its author (ON DELETE SET NULL), and saying so is more
  // honest than attributing it to nobody in particular.
  return comment.author_name ?? "Former member";
}

export function GraphComments({
  workspaceId,
  target,
  currentUserId,
  onActivityChange,
}: {
  workspaceId: string;
  target: CommentTargetRef;
  /** Used only to decide whose comments offer a delete button. */
  currentUserId: string | null;
  /** Called after a post, a delete, or a read, so the canvas badges catch up. */
  onActivityChange: () => void;
}) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  // The callback changes identity on every parent render, so it is read from a
  // ref rather than depended on -- otherwise loading a thread would re-run
  // forever.
  const activityRef = useRef(onActivityChange);

  useEffect(() => {
    activityRef.current = onActivityChange;
  }, [onActivityChange]);

  const { target_kind: targetKind, target_key: targetKey } = target;

  /**
   * Loads the thread, and nothing else: no state is reset here. The parent
   * keys this component on its target, so switching selection remounts it with
   * an empty draft and a fresh loading state. A reload after posting keeps the
   * existing list on screen rather than blanking it.
   */
  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        const params = new URLSearchParams({
          target_kind: targetKind,
          target_key: targetKey,
        });
        const comments = await apiRequest<GraphComment[]>(
          `/api/workspaces/${workspaceId}/graph/comments?${params.toString()}`,
          { signal: controller.signal },
        );
        setState({ kind: "ready", comments });

        // Reading is what clears the mark. Fire and forget: a failed mark means
        // the badge stays, which is recoverable, and blocking the thread on it
        // would be worse.
        if (comments.length > 0) {
          void apiRequest(`/api/workspaces/${workspaceId}/graph/comments/seen`, {
            method: "POST",
            body: JSON.stringify({ target_kind: targetKind, target_key: targetKey }),
          })
            .then(() => activityRef.current())
            .catch(() => undefined);
        }
      } catch (requestError) {
        if (controller.signal.aborted) return;
        if (requestError instanceof ApiError && requestError.status === 401) {
          router.replace("/login");
          return;
        }
        setState({
          kind: "error",
          message:
            requestError instanceof ApiError
              ? requestError.message
              : "Unable to load comments.",
        });
      }
    }

    void load();
    return () => controller.abort();
  }, [router, targetKey, targetKind, version, workspaceId]);

  async function send() {
    const body = draft.trim();
    if (!body || isSending) return;
    setIsSending(true);
    setActionError(null);
    try {
      await apiRequest<GraphComment>(
        `/api/workspaces/${workspaceId}/graph/comments`,
        {
          method: "POST",
          body: JSON.stringify({
            target_kind: targetKind,
            target_key: targetKey,
            body,
          }),
        },
      );
      setDraft("");
      setVersion((current) => current + 1);
      activityRef.current();
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        router.replace("/login");
        return;
      }
      setActionError(
        requestError instanceof ApiError
          ? requestError.message
          : "Could not post the comment. The Cortex server is unreachable.",
      );
    } finally {
      setIsSending(false);
    }
  }

  async function remove(commentId: string) {
    setActionError(null);
    try {
      await apiRequest<void>(
        `/api/workspaces/${workspaceId}/graph/comments/${commentId}`,
        { method: "DELETE" },
      );
      setVersion((current) => current + 1);
      activityRef.current();
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        router.replace("/login");
        return;
      }
      setActionError(
        requestError instanceof ApiError
          ? requestError.message
          : "Could not delete the comment.",
      );
    }
  }

  const comments = state.kind === "ready" ? state.comments : [];

  return (
    <section className="mt-6 border-t border-border/40 pt-5">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
        Comments{comments.length > 0 ? ` (${comments.length})` : ""}
      </h3>

      {state.kind === "loading" ? (
        <p role="status" className="mt-3 text-sm text-muted">
          Loading comments…
        </p>
      ) : null}

      {state.kind === "error" ? (
        <FeedbackAlert message={state.message} />
      ) : null}

      {state.kind === "ready" && comments.length === 0 ? (
        <p className="mt-3 text-sm text-muted">
          No comments yet. Start the discussion for your team.
        </p>
      ) : null}

      {comments.length > 0 ? (
        <ol className="mt-3 space-y-4">
          {comments.map((comment) => (
            <li key={comment.id}>
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-sm font-medium text-foreground">
                  {authorLabel(comment)}
                </p>
                <div className="flex shrink-0 items-center gap-2">
                  <time
                    dateTime={comment.created_at}
                    title={formatAbsoluteTime(comment.created_at)}
                    className="text-xs text-subtle"
                  >
                    {formatRelativeTime(comment.created_at) ?? ""}
                  </time>
                  {currentUserId && comment.author_id === currentUserId ? (
                    <button
                      type="button"
                      onClick={() => void remove(comment.id)}
                      aria-label="Delete comment"
                      className="text-xs font-medium text-subtle transition-colors hover:text-red-300"
                    >
                      Delete
                    </button>
                  ) : null}
                </div>
              </div>
              <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-muted">
                {comment.body}
              </p>
            </li>
          ))}
        </ol>
      ) : null}

      <form
        className="mt-5"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <label htmlFor="graph-comment-body" className="sr-only">
          Add a comment
        </label>
        <textarea
          id="graph-comment-body"
          value={draft}
          maxLength={MAX_LENGTH}
          rows={3}
          disabled={isSending}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Add a comment for your team"
          className="block w-full resize-none rounded-control border border-border/50 bg-surface px-3 py-2 text-sm leading-6 text-foreground placeholder:text-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
        />
        <div className="mt-2 flex items-center justify-end">
          <Button
            type="submit"
            size="small"
            variant="primary"
            disabled={draft.trim().length === 0 || isSending}
          >
            {isSending ? "Posting…" : "Comment"}
          </Button>
        </div>
      </form>

      <FeedbackAlert message={actionError} />
    </section>
  );
}
