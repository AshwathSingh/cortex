"use client";

import {
  type FormEvent,
  type SyntheticEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { Field, fieldControlClassName } from "@/components/ui/form-field";
import { ApiError } from "@/lib/api";
import type { WorkspaceSummary } from "@/lib/api-types";
import { updateWorkspaceProfile } from "@/lib/workspace-client";

const NAME_MAX_LENGTH = 100;
const DESCRIPTION_MAX_LENGTH = 1000;

export function EditWorkspaceModal({
  workspace,
  onClose,
  onSaved,
}: {
  workspace: WorkspaceSummary;
  onClose: () => void;
  onSaved: (workspace: WorkspaceSummary) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(workspace.name);
  const [description, setDescription] = useState(workspace.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    nameRef.current?.focus();
  }, []);

  function closeDialog() {
    if (isSaving) return;
    dialogRef.current?.close();
    onClose();
  }

  function handleCancel(event: SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    closeDialog();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    const trimmedDescription = description.trim();

    if (!trimmedName) {
      setError("Enter a workspace name.");
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      const updatedWorkspace = await updateWorkspaceProfile(workspace.id, {
        name: trimmedName,
        description: trimmedDescription || null,
      });
      onSaved(updatedWorkspace);
      dialogRef.current?.close();
      onClose();
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "Unable to update the workspace.",
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="edit-workspace-title"
      aria-describedby="edit-workspace-description"
      aria-modal="true"
      onCancel={handleCancel}
      className="m-auto w-[min(34rem,calc(100%-2rem))] rounded-2xl border border-border/30 bg-surface p-0 text-foreground shadow-[0_28px_80px_rgb(0_0_0/0.48)] backdrop:bg-background/85 backdrop:backdrop-blur-[2px]"
    >
      <div className="flex items-start justify-between gap-5 border-b border-border/20 px-6 py-5">
        <div>
          <h2
            id="edit-workspace-title"
            className="text-xl font-semibold tracking-[-0.025em]"
          >
            Edit workspace
          </h2>
          <p
            id="edit-workspace-description"
            className="mt-1.5 text-sm leading-5 text-muted"
          >
            Update the name and description shown to every member.
          </p>
        </div>
        <button
          type="button"
          aria-label="Close workspace editor"
          disabled={isSaving}
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
        <Field id="edit-workspace-name" label="Workspace name">
          <input
            ref={nameRef}
            id="edit-workspace-name"
            value={name}
            required
            maxLength={NAME_MAX_LENGTH}
            disabled={isSaving}
            onChange={(event) => setName(event.target.value)}
            className={`${fieldControlClassName} h-11`}
          />
        </Field>

        <Field
          id="edit-workspace-description-field"
          label="Description"
          hint={`Optional · ${description.length}/${DESCRIPTION_MAX_LENGTH}`}
        >
          <textarea
            id="edit-workspace-description-field"
            value={description}
            rows={4}
            maxLength={DESCRIPTION_MAX_LENGTH}
            disabled={isSaving}
            onChange={(event) => setDescription(event.target.value)}
            className={`${fieldControlClassName} resize-y py-3 leading-6`}
          />
        </Field>

        <FeedbackAlert message={error} />

        <div className="flex justify-end gap-2 pt-1">
          <Button
            type="button"
            variant="ghost"
            disabled={isSaving}
            onClick={closeDialog}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={isSaving || !name.trim()}
          >
            {isSaving ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
