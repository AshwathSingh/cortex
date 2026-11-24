"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { SourceConnectionLayout } from "@/components/sources/source-connection-layout";
import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { FormField } from "@/components/ui/form-field";
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
    label: "Pull requests",
    description: "Titles, descriptions, state and authorship.",
  },
  {
    label: "Issues",
    description: "Open and closed work, with its current status.",
  },
  {
    label: "Contributors",
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

  return (
    <SourceConnectionLayout
      backHref={routes.workspace.sources(workspaceId)}
      backLabel="Back to sources"
      sourceName="GitHub"
      workspaceName={workspace?.name ?? "this workspace"}
      description="Add repository activity to this workspace's project memory."
      methodTitle="Connect with a URL"
      methodDescription="Paste the full GitHub URL for the repository you want to connect."
      dataTitle="What Cortex will use from GitHub"
      dataDescription="These artifacts are indexed together for this connection."
      dataItems={indexedArtifacts}
    >
      {isWorkspaceLoading ? (
        <p role="status" className="text-sm text-muted">
          Checking workspace access…
        </p>
      ) : !canManageSources(workspace?.permissions) ? (
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            View-only access
          </h3>
          <p className="mt-2 max-w-xl text-sm leading-6 text-muted">
            Ask a workspace owner or editor to connect a GitHub repository.
          </p>
        </div>
      ) : (
        <form
          onSubmit={handleSubmit}
          noValidate
          aria-label="Add a GitHub repository"
          className="max-w-3xl"
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
                className="mt-5 border-l-2 border-emerald-400/60 pl-3 text-sm leading-6 text-foreground"
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
      )}
    </SourceConnectionLayout>
  );
}
