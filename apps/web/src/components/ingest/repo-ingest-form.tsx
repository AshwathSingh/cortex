"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { IngestResult } from "@/lib/api-types";

const fallbackMessages: Record<number, string> = {
  404: "Repository not found or not accessible.",
  429: "GitHub rate limit reached. Try again later.",
  502: "GitHub returned an unexpected response.",
  503: "Graph database is unavailable.",
};

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; result: IngestResult }
  | { kind: "error"; message: string };

export function RepoIngestForm() {
  const [repoUrl, setRepoUrl] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const url = repoUrl.trim();
    if (!url) {
      setStatus({ kind: "error", message: "Enter a GitHub repository URL." });
      return;
    }

    setStatus({ kind: "loading" });
    try {
      const result = await apiRequest<IngestResult>("/api/ingest/github", {
        method: "POST",
        body: JSON.stringify({ repo_url: url }),
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
    <section aria-labelledby="ingest-heading">
      <Link
        href="/workspaces"
        className="text-sm font-medium text-muted transition-colors hover:text-foreground"
      >
        ← Back to workspaces
      </Link>
      <h1
        id="ingest-heading"
        className="mt-10 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]"
      >
        Add a repository
      </h1>
      <p className="mt-4 text-base leading-7 text-muted">
        Build project memory from a GitHub repository.
      </p>

      <form
        onSubmit={handleSubmit}
        noValidate
        aria-label="Ingest a GitHub repository"
        className="mt-10"
      >
        <label htmlFor="repo-url" className="text-sm font-medium text-foreground">
          GitHub repository URL
        </label>
        <input
          id="repo-url"
          type="url"
          value={repoUrl}
          onChange={(event) => setRepoUrl(event.target.value)}
          placeholder="https://github.com/owner/repo"
          disabled={isLoading}
          autoComplete="off"
          spellCheck={false}
          className="mt-2 h-12 w-full rounded-control border border-border/60 bg-surface/70 px-4 text-foreground outline-none transition placeholder:text-subtle hover:border-border focus:border-accent-bright focus:ring-2 focus:ring-accent-bright/20"
        />
        <button
          type="submit"
          disabled={isLoading}
          className="mt-6 min-h-12 rounded-control bg-accent px-5 text-sm font-semibold text-foreground transition-colors hover:bg-accent-hover disabled:cursor-wait disabled:opacity-60"
        >
          {isLoading ? "Ingesting…" : "Ingest repository"}
        </button>

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
            <p role="status" className="mt-5 text-sm text-foreground">
              Ingested <strong>{status.result.repo}</strong>: {status.result.pull_requests}{" "}
              pull requests, {status.result.issues} issues.
            </p>
          ) : null}
        </div>
      </form>
    </section>
  );
}
