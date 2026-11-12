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

const indexedArtifacts = [
  {
    index: "01",
    title: "Pull requests",
    description: "Titles, descriptions, state and authorship.",
  },
  {
    index: "02",
    title: "Issues",
    description: "Open and closed work, with its current status.",
  },
  {
    index: "03",
    title: "Contributors",
    description: "The people connected to repository activity.",
  },
] as const;

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
      description="Connect the project work your team already tracks in GitHub."
      eyebrow="GitHub source"
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

  if (!canManageSources(workspace?.permissions)) {
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

      <div className="mt-10 grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
        <section
          aria-labelledby="repository-details-heading"
          className="rounded-2xl border border-border/30 bg-surface/45 p-6 sm:p-8"
        >
          <div className="flex items-start gap-4">
            <span
              aria-hidden="true"
              className="grid size-10 shrink-0 place-items-center rounded-xl border border-border/35 bg-surface-raised font-mono text-xs font-semibold text-accent-bright"
            >
              GH
            </span>
            <div>
              <h2
                id="repository-details-heading"
                className="text-base font-semibold text-foreground"
              >
                Repository details
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted">
                Paste the URL of the repository you want this workspace to remember.
              </p>
            </div>
          </div>

          <form
            onSubmit={handleSubmit}
            noValidate
            aria-label="Add a GitHub repository"
            className="mt-8"
          >
            <FormField
              id="repo-url"
              label="GitHub repository URL"
              hint="owner/repository"
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
              className="mt-6 w-full disabled:cursor-wait sm:w-auto"
            >
              {isLoading ? "Adding repository…" : "Add repository"}
            </Button>

            <div aria-live="polite">
              {isLoading ? (
                <p className="mt-5 text-sm leading-6 text-muted">
                  Reading pull requests and issues. Large repositories can take a
                  while.
                </p>
              ) : null}
              <FeedbackAlert
                message={status.kind === "error" ? status.message : null}
              />
              {status.kind === "success" ? (
                <div
                  role="status"
                  className="mt-5 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.06] px-4 py-3 text-sm text-foreground"
                >
                  <p>
                    Added <strong>{status.result.repo}</strong>:{" "}
                    {status.result.pull_requests} pull requests and{" "}
                    {status.result.issues} issues.
                  </p>
                  <Link
                    href={routes.workspace.sources(workspaceId)}
                    className="mt-2 inline-block font-semibold text-accent-bright transition-colors hover:text-foreground"
                  >
                    View sources →
                  </Link>
                </div>
              ) : null}
            </div>
          </form>
        </section>

        <aside
          aria-labelledby="indexed-artifacts-heading"
          className="rounded-2xl border border-border/25 bg-surface/25 p-6"
        >
          <p className="font-mono text-[0.625rem] font-semibold uppercase tracking-[0.14em] text-subtle">
            After connecting
          </p>
          <h2
            id="indexed-artifacts-heading"
            className="mt-2 text-base font-semibold text-foreground"
          >
            What Cortex indexes
          </h2>
          <ol className="mt-5 divide-y divide-border/20">
            {indexedArtifacts.map((artifact) => (
              <li key={artifact.index} className="flex gap-3 py-4 first:pt-0">
                <span className="font-mono text-[0.625rem] font-semibold text-accent-bright">
                  {artifact.index}
                </span>
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {artifact.title}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-muted">
                    {artifact.description}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <p className="border-t border-border/20 pt-4 text-xs leading-5 text-subtle">
            You can re-sync the repository later from Sources.
          </p>
        </aside>
      </div>
    </section>
  );
}
