"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { WorkspaceSummary } from "@/lib/api-types";

// Mirrors the limits enforced by POST /api/workspaces.
export const NAME_MAX_LENGTH = 100;
export const DESCRIPTION_MAX_LENGTH = 1000;

const fieldClassName =
  "mt-2 w-full rounded-control border border-border/60 bg-surface/70 px-4 text-[0.95rem] text-foreground outline-none transition placeholder:text-subtle hover:border-border focus:border-accent-bright focus:ring-2 focus:ring-accent-bright/20 disabled:opacity-60";

function validate(name: string, description: string): string | null {
  if (!name) return "Enter a workspace name.";
  if (name.length > NAME_MAX_LENGTH) {
    return `Workspace name must be ${NAME_MAX_LENGTH} characters or fewer.`;
  }
  if (description.length > DESCRIPTION_MAX_LENGTH) {
    return `Description must be ${DESCRIPTION_MAX_LENGTH} characters or fewer.`;
  }
  return null;
}

function errorMessage(requestError: unknown): string {
  if (!(requestError instanceof ApiError)) {
    return "Unable to reach Cortex. Please try again.";
  }
  // 409 carries a readable detail; 422 carries FastAPI's validation list.
  if (requestError.status === 422) {
    return "Check the workspace name and description, then try again.";
  }
  return requestError.message === "API request failed"
    ? `Unable to create the workspace (${requestError.status}).`
    : requestError.message;
}

export function CreateWorkspaceForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    const trimmedDescription = description.trim();

    const validationError = validate(trimmedName, trimmedDescription);
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    setIsSubmitting(true);
    try {
      const workspace = await apiRequest<WorkspaceSummary>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({
          name: trimmedName,
          description: trimmedDescription || null,
        }),
      });
      // Stay disabled while navigating so a second click cannot create a duplicate.
      router.push(`/workspaces/${workspace.id}`);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        router.replace("/login");
        return;
      }
      setError(errorMessage(requestError));
      setIsSubmitting(false);
    }
  }

  return (
    <section aria-labelledby="create-workspace-heading">
      <Link
        href="/workspaces"
        className="text-sm font-medium text-muted transition-colors hover:text-foreground"
      >
        ← All workspaces
      </Link>
      <h1
        id="create-workspace-heading"
        className="mt-10 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]"
      >
        New workspace
      </h1>
      <p className="mt-4 text-base leading-7 text-muted">
        A workspace holds the repositories and project memory for one team or
        project.
      </p>

      <form
        onSubmit={handleSubmit}
        noValidate
        aria-label="Create a workspace"
        className="mt-10 space-y-6"
      >
        <div>
          <label
            htmlFor="workspace-name"
            className="text-sm font-medium text-foreground"
          >
            Workspace name
          </label>
          <input
            id="workspace-name"
            name="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Cortex platform"
            maxLength={NAME_MAX_LENGTH}
            disabled={isSubmitting}
            autoComplete="off"
            required
            aria-invalid={error !== null && !name.trim() ? true : undefined}
            className={`${fieldClassName} h-12`}
          />
        </div>

        <div>
          <div className="flex items-baseline justify-between gap-4">
            <label
              htmlFor="workspace-description"
              className="text-sm font-medium text-foreground"
            >
              Description
            </label>
            <span id="workspace-description-hint" className="text-xs text-subtle">
              Optional · {description.length}/{DESCRIPTION_MAX_LENGTH}
            </span>
          </div>
          <textarea
            id="workspace-description"
            name="description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="What is this workspace for?"
            maxLength={DESCRIPTION_MAX_LENGTH}
            rows={4}
            disabled={isSubmitting}
            aria-describedby="workspace-description-hint"
            className={`${fieldClassName} resize-y py-3 leading-6`}
          />
        </div>

        <div aria-live="polite">
          <FeedbackAlert message={error} />
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="min-h-12 rounded-control bg-accent px-5 text-sm font-semibold text-foreground transition-colors hover:bg-accent-hover disabled:cursor-wait disabled:opacity-60"
        >
          {isSubmitting ? "Creating…" : "Create workspace"}
        </button>
      </form>
    </section>
  );
}
