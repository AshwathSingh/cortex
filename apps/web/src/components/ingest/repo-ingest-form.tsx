"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { FormField } from "@/components/ui/form-field";
import { PageHeader } from "@/components/ui/page-layout";
import { useWorkspace } from "@/components/workspaces/workspace-context";
import { ApiError, apiRequest } from "@/lib/api";
import type { IngestResult } from "@/lib/api-types";
import { routes } from "@/lib/routes";
import { canManageSources } from "@/lib/workspace-permissions";

const fallbackMessages: Record<number, string> = {
  403: "You need edit access to this workspace to add a repository.",
  404: "Repository not found or not accessible.",
  429: "GitHub rate limit reached. Try again later.",
  502: "GitHub returned an unexpected response.",
  503: "Graph database is unavailable.",
};

/** Add `https://` when no scheme is given, so `github.com/owner/repo` works. */
export function normalizeRepoUrl(input: string): string {
  const url = input.trim();
  return url && !url.includes("://") ? `https://${url}` : url;
}

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; result: IngestResult }
  | { kind: "error"; message: string };

export function RepoIngestForm({ workspaceId }: { workspaceId: string }) {
  const { workspace, isLoading: isWorkspaceLoading } = useWorkspace();
  const [repoUrl, setRepoUrl] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const url = normalizeRepoUrl(repoUrl);
    if (!url) {
      setStatus({ kind: "error", message: "Enter a GitHub repository URL." });
      return;
    }
    setRepoUrl(url);

    setStatus({ kind: "loading" });
    try {
      const result = await apiRequest<IngestResult>("/api/ingest/github", {
        method: "POST",
        body: JSON.stringify({ repo_url: url, workspace_id: workspaceId }),
      });
      setStatus({ kind: "success", result });
    } catch (requestError) {
      const message =
        requestError instanceof ApiError
          ? requestError.message === "API request failed"
            ? fallbackMessages[requestError.status] ??
              `Request failed (${requestError.status}).`
            : requestError.message
          : "Could not reach the Cortex server.";
      setStatus({ kind: "error", message });
    }
  }

  const isLoading = status.kind === "loading";
  const header = (
    <PageHeader
      backHref={routes.workspace.sources(workspaceId)}
      backLabel="Back to sources"
      description="Build project memory from a GitHub repository."
      headingId="ingest-heading"
      title="Add a repository"
    />
  );

  if (isWorkspaceLoading) {
    return (
      <section aria-labelledby="ingest-heading">
        {header}
        <p role="status" className="mt-10 text-sm text-muted">
          Checking workspace access…
        </p>
      </section>
    );
  }

  if (!canManageSources(workspace?.role)) {
    return (
      <section aria-labelledby="ingest-heading">
        {header}
        <div className="mt-10 border-y border-border/25 py-8">
          <h2 className="text-base font-semibold text-foreground">
            View-only access
          </h2>
          <p className="mt-2 max-w-xl text-sm leading-6 text-muted">
            Ask a workspace owner or editor to connect a GitHub repository.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="ingest-heading">
      {header}

      <form
        onSubmit={handleSubmit}
        noValidate
        aria-label="Ingest a GitHub repository"
        className="mt-10"
      >
        <FormField
          id="repo-url"
          label="GitHub repository URL"
          type="text"
          inputMode="url"
          value={repoUrl}
          onChange={(event) => setRepoUrl(event.target.value)}
          placeholder="github.com/owner/repo"
          disabled={isLoading}
          autoComplete="off"
          spellCheck={false}
        />
        <Button
          type="submit"
          disabled={isLoading}
          size="large"
          variant="primary"
          className="mt-6 disabled:cursor-wait"
        >
          {isLoading ? "Ingesting…" : "Ingest repository"}
        </Button>

        <div aria-live="polite">
          {isLoading ? (
            <p className="mt-5 text-sm text-muted">
              Fetching pull requests and issues. Large repositories can take a while.
            </p>
          ) : null}
          <FeedbackAlert
            message={status.kind === "error" ? status.message : null}
          />
          {status.kind === "success" ? (
            <div role="status" className="mt-5 text-sm text-foreground">
              <p>
                Ingested <strong>{status.result.repo}</strong>:{" "}
                {status.result.pull_requests} pull requests, {status.result.issues}{" "}
                issues.
              </p>
              <Link href={routes.workspace.sources(workspaceId)} className="mt-3 inline-block font-semibold text-accent-bright transition-colors hover:text-foreground">
                View sources →
              </Link>
            </div>
          ) : null}
        </div>
      </form>
    </section>
  );
}
