"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { AuthenticatedUser, WorkspaceSummary } from "@/lib/api-types";

export function WorkspaceSelector() {
  const router = useRouter();
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    async function loadWorkspaceData() {
      try {
        const [currentUser, availableWorkspaces] = await Promise.all([
          apiRequest<AuthenticatedUser>("/api/auth/me", {
            signal: controller.signal,
          }),
          apiRequest<WorkspaceSummary[]>("/api/workspaces", {
            signal: controller.signal,
          }),
        ]);
        setUser(currentUser);
        setWorkspaces(availableWorkspaces);
      } catch (requestError) {
        if (controller.signal.aborted) {
          return;
        }
        if (requestError instanceof ApiError && requestError.status === 401) {
          router.replace("/login");
          return;
        }
        setError(
          requestError instanceof ApiError
            ? requestError.message
            : "Unable to load your workspaces.",
        );
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    }

    void loadWorkspaceData();
    return () => controller.abort();
  }, [router]);

  async function logout() {
    setIsLoggingOut(true);
    setError(null);
    try {
      await apiRequest<void>("/api/auth/logout", { method: "POST" });
      router.replace("/login");
      router.refresh();
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "Unable to log out. Please try again.",
      );
      setIsLoggingOut(false);
    }
  }

  return (
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[64rem]">
        <header className="flex items-center justify-between gap-4 border-b border-border/30 pb-6">
          <Link
            href="/"
            className="text-[1.35rem] font-semibold tracking-[-0.025em] text-foreground"
          >
            Cortex
          </Link>
          <button
            type="button"
            disabled={isLoggingOut}
            onClick={logout}
            className="min-h-11 rounded-control border border-border/50 px-4 text-sm font-medium text-muted transition-colors hover:border-border hover:text-foreground disabled:cursor-wait disabled:opacity-60"
          >
            {isLoggingOut ? "Logging out…" : "Log out"}
          </button>
        </header>

        <section aria-labelledby="workspace-heading" className="py-14 sm:py-20">
          <p className="text-sm font-medium text-accent-bright">
            {user?.display_name ?? user?.email ?? "Your Cortex account"}
          </p>
          <h1
            id="workspace-heading"
            className="mt-3 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]"
          >
            Choose a workspace
          </h1>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
            <p className="max-w-2xl text-base leading-7 text-muted">
              Open a project context you own or collaborate on.
            </p>
            <Link
              href="/workspaces/new"
              className="inline-flex min-h-11 items-center rounded-control bg-accent px-5 text-sm font-semibold text-foreground transition-colors hover:bg-accent-hover"
            >
              New workspace
            </Link>
          </div>

          <FeedbackAlert message={error} />

          {isLoading ? (
            <p className="mt-10 text-sm text-muted">Loading workspaces…</p>
          ) : (
            <div className="mt-10 grid gap-4 sm:grid-cols-2">
              {workspaces.map((workspace) => (
                <Link
                  key={workspace.id}
                  href={`/workspaces/${workspace.id}`}
                  className="rounded-panel border border-border/40 bg-surface/70 p-6 transition-colors hover:border-border-strong/70 hover:bg-surface-raised"
                >
                  <div className="flex items-start justify-between gap-4">
                    <h2 className="text-xl font-semibold text-foreground">
                      {workspace.name}
                    </h2>
                    <span className="rounded-full border border-border/40 px-2.5 py-1 text-[0.65rem] font-semibold tracking-[0.08em] text-accent-bright">
                      {workspace.role}
                    </span>
                  </div>
                  {workspace.description ? (
                    <p className="mt-3 line-clamp-2 text-sm leading-6 text-muted">
                      {workspace.description}
                    </p>
                  ) : null}
                  <p className="mt-8 text-xs text-subtle">
                    Created {new Date(workspace.created_at).toLocaleDateString()}
                  </p>
                </Link>
              ))}
            </div>
          )}

          {!isLoading && !error && workspaces.length === 0 ? (
            <p className="mt-10 rounded-panel border border-border/40 bg-surface/60 p-6 text-muted">
              You do not have access to any workspaces yet.{" "}
              <Link
                href="/workspaces/new"
                className="font-semibold text-accent-bright transition-colors hover:text-foreground"
              >
                Create one
              </Link>
              .
            </p>
          ) : null}
        </section>
      </div>
    </main>
  );
}
