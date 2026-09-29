"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { WorkspaceSummary } from "@/lib/api-types";

export function WorkspaceDetail({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadWorkspace() {
      try {
        const result = await apiRequest<WorkspaceSummary>(
          `/api/workspaces/${workspaceId}`,
          { signal: controller.signal },
        );
        setWorkspace(result);
      } catch (requestError) {
        if (controller.signal.aborted) return;
        if (requestError instanceof ApiError && requestError.status === 401) {
          router.replace("/login");
          return;
        }
        setError(
          requestError instanceof ApiError
            ? requestError.message
            : "Unable to load this workspace.",
        );
      }
    }

    void loadWorkspace();
    return () => controller.abort();
  }, [router, workspaceId]);

  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[64rem]">
        <Link
          href="/workspaces"
          className="text-sm font-medium text-muted transition-colors hover:text-foreground"
        >
          ← All workspaces
        </Link>
        <FeedbackAlert message={error} />
        {!workspace && !error ? (
          <p className="mt-10 text-sm text-muted">Loading workspace…</p>
        ) : null}
        {workspace ? (
          <section className="mt-10" aria-labelledby="workspace-title">
            <p className="text-sm font-medium text-accent-bright">
              {workspace.role}
            </p>
            <h1
              id="workspace-title"
              className="mt-3 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]"
            >
              {workspace.name}
            </h1>
            {workspace.description ? (
              <p className="mt-5 max-w-2xl whitespace-pre-line text-base leading-7 text-muted">
                {workspace.description}
              </p>
            ) : null}
            <p className="mt-4 text-sm text-subtle">
              Created {new Date(workspace.created_at).toLocaleDateString()}
            </p>
            <Link
              href="/ingest"
              className="mt-10 inline-flex min-h-11 items-center rounded-control bg-accent px-5 text-sm font-semibold text-foreground transition-colors hover:bg-accent-hover"
            >
              Add a GitHub repository
            </Link>
          </section>
        ) : null}
      </div>
    </main>
  );
}
