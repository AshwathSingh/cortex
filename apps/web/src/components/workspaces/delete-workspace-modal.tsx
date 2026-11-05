"use client";

import {
  type FormEvent,
  type SyntheticEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { Field, fieldControlClassName } from "@/components/ui/form-field";
import { ApiError } from "@/lib/api";
import type { WorkspaceSummary } from "@/lib/api-types";
import { forgetLastWorkspace } from "@/lib/last-workspace";
import { routes } from "@/lib/routes";
import { deleteWorkspace } from "@/lib/workspace-client";
import {
  forgetPendingWorkspaceDeletion,
  rememberPendingWorkspaceDeletion,
} from "@/lib/workspace-delete-recovery";

function deleteErrorMessage(error: unknown) {
  if (!(error instanceof ApiError)) {
    return "Unable to delete the workspace. Check your connection and try again.";
  }
  if (error.status === 401) {
    return "Your session has expired. Sign in again before deleting this workspace.";
  }
  if (error.status === 403) {
    return "You no longer have permission to delete this workspace. Only the workspace owner can delete it.";
  }
  if (error.status === 400) {
    return "The workspace name may have changed. Close this dialog, refresh the page, and try again.";
  }
  return error.message;
}

export function DeleteWorkspaceModal({
  workspace,
  userId,
  onClose,
}: {
  workspace: WorkspaceSummary;
  userId: string;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const confirmationRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const isConfirmed = confirmation === workspace.name;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    confirmationRef.current?.focus();
  }, []);

  function closeDialog() {
    if (isDeleting) return;
    dialogRef.current?.close();
    onClose();
  }

  function handleCancel(event: SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    closeDialog();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isConfirmed || isDeleting) return;

    setIsDeleting(true);
    setError(null);
    try {
      await deleteWorkspace(workspace.id, confirmation);
      forgetPendingWorkspaceDeletion(userId, workspace.id);
      forgetLastWorkspace(userId);
      router.replace(routes.workspaces);
    } catch (requestError) {
      setError(deleteErrorMessage(requestError));
      setIsDeleting(false);
      if (requestError instanceof ApiError && requestError.status === 401) {
        setNeedsSignIn(true);
        return;
      }
      if (requestError instanceof ApiError && requestError.status >= 500) {
        const recoverySaved = rememberPendingWorkspaceDeletion(userId, {
          workspaceId: workspace.id,
          workspaceName: workspace.name,
        });
        if (recoverySaved) router.replace(routes.workspaces);
      }
    }
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="delete-workspace-title"
      aria-describedby="delete-workspace-description"
      aria-modal="true"
      onCancel={handleCancel}
      className="m-auto w-[min(34rem,calc(100%-2rem))] rounded-2xl border border-red-400/25 bg-surface p-0 text-foreground shadow-[0_28px_80px_rgb(0_0_0/0.55)] backdrop:bg-background/85 backdrop:backdrop-blur-[2px]"
    >
      <div className="flex items-start justify-between gap-5 border-b border-red-400/15 px-6 py-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-red-300">
            Permanent action
          </p>
          <h2
            id="delete-workspace-title"
            className="mt-1.5 text-xl font-semibold tracking-[-0.025em]"
          >
            Delete {workspace.name}?
          </h2>
          <p
            id="delete-workspace-description"
            className="mt-2 text-sm leading-6 text-muted"
          >
            This permanently deletes the workspace, members, pending invites,
            connected sources, and graph data. This cannot be undone.
          </p>
        </div>
        <button
          type="button"
          aria-label="Close delete workspace confirmation"
          disabled={isDeleting}
          onClick={closeDialog}
          className="grid size-8 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-surface-raised hover:text-foreground disabled:opacity-50"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 20 20"
            className="size-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          >
            <path d="m5 5 10 10M15 5 5 15" />
          </svg>
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5 px-6 py-6">
        <div className="rounded-xl border border-red-400/20 bg-red-500/5 px-4 py-3">
          <p className="text-sm font-medium text-red-200">
            All project memory and connections in this workspace will be removed.
          </p>
        </div>

        <Field
          id="delete-workspace-confirmation"
          label={`Type ${workspace.name} to confirm`}
          hint="Case-sensitive"
        >
          <input
            ref={confirmationRef}
            id="delete-workspace-confirmation"
            value={confirmation}
            autoComplete="off"
            aria-describedby="delete-workspace-confirmation-hint"
            disabled={isDeleting || needsSignIn}
            onChange={(event) => {
              setConfirmation(event.target.value);
              if (!needsSignIn) setError(null);
            }}
            className={`${fieldControlClassName} h-11 border-red-400/30 focus:border-red-300/80 focus:ring-red-400/15`}
          />
        </Field>

        <FeedbackAlert message={error} />

        <div className="flex justify-end gap-2 pt-1">
          <Button
            type="button"
            variant="ghost"
            disabled={isDeleting}
            onClick={closeDialog}
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
              disabled={isDeleting || !isConfirmed}
            >
              {isDeleting ? "Deleting workspace…" : "Delete workspace"}
            </Button>
          )}
        </div>
      </form>
    </dialog>
  );
}
