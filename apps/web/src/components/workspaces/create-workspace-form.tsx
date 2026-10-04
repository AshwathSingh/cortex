"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import {
  Field,
  fieldControlClassName,
  FormField,
} from "@/components/ui/form-field";
import { PageHeader } from "@/components/ui/page-layout";
import { ApiError, apiRequest } from "@/lib/api";
import type { WorkspaceSummary } from "@/lib/api-types";
import { routes } from "@/lib/routes";

// Mirrors the limits enforced by POST /api/workspaces.
export const NAME_MAX_LENGTH = 100;
export const DESCRIPTION_MAX_LENGTH = 1000;

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
      <PageHeader
        backHref={routes.workspaceSelector}
        backLabel="All workspaces"
        description="A workspace holds the repositories and project memory for one team or project."
        headingId="create-workspace-heading"
        title="New workspace"
      />

      <form
        onSubmit={handleSubmit}
        noValidate
        aria-label="Create a workspace"
        className="mt-10 space-y-6"
      >
        <FormField
          id="workspace-name"
          label="Workspace name"
          name="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Cortex platform"
          maxLength={NAME_MAX_LENGTH}
          disabled={isSubmitting}
          autoComplete="off"
          required
          aria-invalid={error !== null && !name.trim() ? true : undefined}
        />

        <Field
          id="workspace-description"
          label="Description"
          hint={`Optional · ${description.length}/${DESCRIPTION_MAX_LENGTH}`}
        >
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
            className={`${fieldControlClassName} resize-y py-3 leading-6`}
          />
        </Field>

        <div aria-live="polite">
          <FeedbackAlert message={error} />
        </div>

        <Button
          type="submit"
          disabled={isSubmitting}
          size="large"
          variant="primary"
          className="disabled:cursor-wait"
        >
          {isSubmitting ? "Creating…" : "Create workspace"}
        </Button>
      </form>
    </section>
  );
}
