"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { SourceStatus } from "@/components/sources/source-status";
import { Button, buttonClassName } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { PageHeader, PageShell } from "@/components/ui/page-layout";
import { useWorkspace } from "@/components/workspaces/workspace-context";
import { ApiError, apiRequest } from "@/lib/api";
import type { IngestResult, WorkspaceSource } from "@/lib/api-types";
import { routes } from "@/lib/routes";
import { canManageSources } from "@/lib/workspace-permissions";

type State =
  | { kind: "loading" }
  | { kind: "ready"; sources: WorkspaceSource[] }
  | { kind: "error"; message: string };

/**
 * How often the list refreshes while an ingestion is running.
 *
 * Ingestion is synchronous server-side (US-7 has no job queue), so a large repo
 * holds the POST open for minutes and the request can easily outlive the page.
 * Polling is what gets the row to SUCCESS or FAILED either way -- the server
 * keeps going, and `data_sources` is where it reports.
 */
const SYNC_POLL_MS = 5_000;

function RepositoryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="size-5">
      <path d="M5 4.5A2.5 2.5 0 0 1 7.5 2H19v17H7.5A2.5 2.5 0 0 0 5 21.5v-17Z" />
      <path d="M5 18.5A2.5 2.5 0 0 1 7.5 16H19M9 6h6" />
    </svg>
  );
}

function ArrowUpRightIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="size-4">
      <path d="M6 14 14 6M7 6h7v7" />
    </svg>
  );
}

function githubUrl(repo: string) {
  return `https://github.com/${repo.split("/").map(encodeURIComponent).join("/")}`;
}

function itemLabel(count: number, singular: string) {
  return `${count.toLocaleString()} ${count === 1 ? singular : `${singular}s`}`;
}

export function SourceInventory({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const { workspace, isLoading: isWorkspaceLoading } = useWorkspace();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [requestVersion, setRequestVersion] = useState(0);
  const [syncingRepo, setSyncingRepo] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const resyncControllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => resyncControllerRef.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();

    async function loadSources() {
      try {
        const sources = await apiRequest<WorkspaceSource[]>(
          `/api/workspaces/${workspaceId}/sources`,
          { signal: controller.signal },
        );
        setState({ kind: "ready", sources });
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
              : "Unable to load workspace sources.",
        });
      }
    }

    void loadSources();
    return () => controller.abort();
  }, [requestVersion, router, workspaceId]);

  const sources = state.kind === "ready" ? state.sources : [];
  const canAddSources = canManageSources(workspace?.role);
  const indexedItems = sources.reduce(
    (total, source) => total + source.total_items,
    0,
  );
  // The row the user just clicked counts as syncing before the server reports
  // it, so polling starts immediately rather than after the first poll.
  const isSyncing =
    syncingRepo !== null || sources.some((source) => source.status === "PENDING");

  useEffect(() => {
    if (!isSyncing) return;
    // Bumping the version re-runs the loader without flipping back to the
    // loading state, so a poll never blanks the list.
    const timer = setInterval(
      () => setRequestVersion((version) => version + 1),
      SYNC_POLL_MS,
    );
    return () => clearInterval(timer);
  }, [isSyncing]);

  /**
   * Re-ingest a repository that is already connected. The repo is known, so
   * this needs no form -- it is the same `POST /api/ingest/github` the ingest
   * page sends, which upserts the source to PENDING before it starts fetching.
   *
   * One ingestion at a time: it is heavy and shares the workspace's GitHub rate
   * limit, so every button is disabled while any source in the workspace is
   * PENDING -- including one somebody else started, which the poll reports.
   */
  async function resync(repo: string) {
    const controller = new AbortController();
    resyncControllerRef.current = controller;
    setSyncError(null);
    setSyncingRepo(repo);

    try {
      await apiRequest<IngestResult>("/api/ingest/github", {
        method: "POST",
        body: JSON.stringify({
          repo_url: githubUrl(repo),
          workspace_id: workspaceId,
        }),
        signal: controller.signal,
      });
    } catch (requestError) {
      if (controller.signal.aborted) return;
      if (requestError instanceof ApiError && requestError.status === 401) {
        router.replace("/login");
        return;
      }
      // The server records its own failures against the source, so the row will
      // carry the reason. This covers what never reached it.
      setSyncError(
        requestError instanceof ApiError
          ? requestError.message
          : `Could not re-sync ${repo}. The Cortex server is unreachable.`,
      );
    } finally {
      if (!controller.signal.aborted) {
        setSyncingRepo(null);
        setRequestVersion((version) => version + 1);
      }
      if (resyncControllerRef.current === controller) {
        resyncControllerRef.current = null;
      }
    }
  }

  return (
    <PageShell>
      <PageHeader
        headingId="sources-title"
        eyebrow="Knowledge inputs"
        title="Sources"
        description="Repositories Cortex uses to build this workspace's project memory."
        action={canAddSources ? (
          <Link
            href={routes.workspace.ingest(workspaceId)}
            className={buttonClassName({ variant: "primary" })}
          >
            Add repository
          </Link>
        ) : undefined}
      />

      {state.kind === "loading" || isWorkspaceLoading ? (
        <p role="status" className="mt-12 text-sm text-muted">
          Loading sources…
        </p>
      ) : null}

      {state.kind === "error" ? (
        <div className="mt-10 max-w-2xl">
          <FeedbackAlert message={state.message} />
          <button
            type="button"
            onClick={() => {
              setState({ kind: "loading" });
              setRequestVersion((version) => version + 1);
            }}
            className="mt-4 text-sm font-semibold text-accent-bright transition-colors hover:text-foreground"
          >
            Try again
          </button>
        </div>
      ) : null}

      {state.kind === "ready" && !isWorkspaceLoading && sources.length === 0 ? (
        <EmptyState
          icon={<RepositoryIcon />}
          title={canAddSources ? "Connect your first source" : "No indexed sources yet"}
          description={
            canAddSources
              ? "Add a GitHub repository to index its pull requests and issues."
              : "Ask a workspace owner or editor to connect a GitHub repository."
          }
          action={canAddSources ? (
            <Link
              href={routes.workspace.ingest(workspaceId)}
              className={buttonClassName({ className: "mt-6" })}
            >
              Add GitHub repository
            </Link>
          ) : undefined}
        />
      ) : null}

      {state.kind === "ready" && !isWorkspaceLoading && sources.length > 0 ? (
        <section aria-labelledby="indexed-sources-heading" className="mt-12">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/30 pb-4">
            <div>
              <h2
                id="indexed-sources-heading"
                className="text-base font-semibold text-foreground"
              >
                Indexed repositories
              </h2>
              <p className="mt-1 text-sm text-muted">
                {itemLabel(sources.length, "source")} ·{" "}
                {itemLabel(indexedItems, "item")} indexed
              </p>
            </div>
          </div>

          <FeedbackAlert message={syncError} />

          <ul className="divide-y divide-border/20">
            {sources.map((source) => {
              const isResyncing = syncingRepo === source.repo;
              return (
                <li
                  key={`${source.kind}:${source.repo}`}
                  className="grid gap-5 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                >
                  <div className="flex min-w-0 items-center gap-4">
                    <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-border/30 bg-surface-raised text-muted">
                      <RepositoryIcon />
                    </span>
                    <div className="min-w-0">
                      <a
                        href={githubUrl(source.repo)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex max-w-full items-center gap-1.5 font-medium text-foreground transition-colors hover:text-accent-bright"
                      >
                        <span className="truncate">{source.repo}</span>
                        <ArrowUpRightIcon />
                        <span className="sr-only"> (opens on GitHub)</span>
                      </a>
                      <SourceStatus
                        source={isResyncing ? { ...source, status: "PENDING" } : source}
                      />
                    </div>
                  </div>
                  <div className="flex items-center justify-end gap-6">
                    <dl className="grid grid-cols-3 gap-6 text-right">
                      <div>
                        <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-subtle">
                          Pull requests
                        </dt>
                        <dd className="mt-1 font-mono text-sm text-foreground">
                          {source.pull_requests.toLocaleString()}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-subtle">
                          Issues
                        </dt>
                        <dd className="mt-1 font-mono text-sm text-foreground">
                          {source.issues.toLocaleString()}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-subtle">
                          Indexed
                        </dt>
                        <dd className="mt-1 font-mono text-sm text-foreground">
                          {source.total_items.toLocaleString()}
                        </dd>
                      </div>
                    </dl>
                    {canAddSources ? (
                      <Button
                        type="button"
                        size="small"
                        variant="muted"
                        aria-label={`Re-sync ${source.repo}`}
                        onClick={() => void resync(source.repo)}
                        disabled={isSyncing || source.status === "PENDING"}
                      >
                        Re-sync
                      </Button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </PageShell>
  );
}
