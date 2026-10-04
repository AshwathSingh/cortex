"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { WorkspaceSource } from "@/lib/api-types";
import { routes } from "@/lib/routes";

type State =
  | { kind: "loading" }
  | { kind: "ready"; sources: WorkspaceSource[] }
  | { kind: "error"; message: string };

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
  const [state, setState] = useState<State>({ kind: "loading" });
  const [requestVersion, setRequestVersion] = useState(0);

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
  const indexedItems = sources.reduce(
    (total, source) => total + source.total_items,
    0,
  );

  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[64rem]">
        <header className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="text-sm font-medium text-accent-bright">Knowledge inputs</p>
            <h1 className="mt-3 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]">Sources</h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-muted">
              Repositories Cortex uses to build this workspace&apos;s project memory.
            </p>
          </div>
          <Link href={routes.workspace.ingest(workspaceId)} className="inline-flex min-h-10 items-center rounded-lg bg-accent px-4 text-sm font-semibold text-foreground transition-colors hover:bg-accent-hover">
            Add repository
          </Link>
        </header>

        {state.kind === "loading" ? <p role="status" className="mt-12 text-sm text-muted">Loading sources…</p> : null}

        {state.kind === "error" ? (
          <div className="mt-10 max-w-2xl">
            <FeedbackAlert message={state.message} />
            <button type="button" onClick={() => { setState({ kind: "loading" }); setRequestVersion((version) => version + 1); }} className="mt-4 text-sm font-semibold text-accent-bright transition-colors hover:text-foreground">
              Try again
            </button>
          </div>
        ) : null}

        {state.kind === "ready" && sources.length === 0 ? (
          <section className="mt-12 border-y border-border/25 py-16 text-center">
            <span className="mx-auto grid size-11 place-items-center rounded-xl border border-border/35 bg-surface-raised text-muted"><RepositoryIcon /></span>
            <h2 className="mt-5 text-lg font-semibold text-foreground">Connect your first source</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted">Add a GitHub repository to index its pull requests and issues.</p>
            <Link href={routes.workspace.ingest(workspaceId)} className="mt-6 inline-flex min-h-10 items-center rounded-lg border border-border/40 px-4 text-sm font-semibold text-foreground transition-colors hover:border-border hover:bg-surface-raised">
              Add GitHub repository
            </Link>
          </section>
        ) : null}

        {state.kind === "ready" && sources.length > 0 ? (
          <section aria-labelledby="indexed-sources-heading" className="mt-12">
            <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/30 pb-4">
              <div>
                <h2 id="indexed-sources-heading" className="text-base font-semibold text-foreground">Indexed repositories</h2>
                <p className="mt-1 text-sm text-muted">{itemLabel(sources.length, "source")} · {itemLabel(indexedItems, "item")} indexed</p>
              </div>
            </div>
            <ul className="divide-y divide-border/20">
              {sources.map((source) => (
                <li key={source.repo} className="grid gap-5 py-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                  <div className="flex min-w-0 items-center gap-4">
                    <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-border/30 bg-surface-raised text-muted"><RepositoryIcon /></span>
                    <div className="min-w-0">
                      <a href={githubUrl(source.repo)} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1.5 font-medium text-foreground transition-colors hover:text-accent-bright">
                        <span className="truncate">{source.repo}</span><ArrowUpRightIcon /><span className="sr-only"> (opens on GitHub)</span>
                      </a>
                      <p className="mt-1 flex items-center gap-2 text-xs text-muted"><span className="size-1.5 rounded-full bg-emerald-400" />Indexed</p>
                    </div>
                  </div>
                  <dl className="grid grid-cols-3 gap-6 text-right">
                    <div><dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-subtle">Pull requests</dt><dd className="mt-1 font-mono text-sm text-foreground">{source.pull_requests.toLocaleString()}</dd></div>
                    <div><dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-subtle">Issues</dt><dd className="mt-1 font-mono text-sm text-foreground">{source.issues.toLocaleString()}</dd></div>
                    <div><dt className="text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-subtle">Indexed</dt><dd className="mt-1 font-mono text-sm text-foreground">{source.total_items.toLocaleString()}</dd></div>
                  </dl>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </main>
  );
}
