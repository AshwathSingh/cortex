"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, buttonClassName } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { PageHeader, PageShell } from "@/components/ui/page-layout";
import { RoleBadge } from "@/components/workspaces/role-badge";
import { ApiError, apiRequest } from "@/lib/api";
import type { AuthenticatedUser, WorkspaceSummary } from "@/lib/api-types";
import {
  forgetLastWorkspace,
  getLastWorkspaceId,
  rememberLastWorkspace,
} from "@/lib/last-workspace";
import { routes } from "@/lib/routes";
import { deleteWorkspace } from "@/lib/workspace-client";
import {
  forgetPendingWorkspaceDeletion,
  getPendingWorkspaceDeletions,
  type PendingWorkspaceDeletion,
} from "@/lib/workspace-delete-recovery";

export function WorkspaceSelector() {
  const router = useRouter();
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [pendingDeletions, setPendingDeletions] = useState<
    PendingWorkspaceDeletion[]
  >([]);
  const [retryingWorkspaceId, setRetryingWorkspaceId] = useState<string | null>(
    null,
  );

  useEffect(() => {
    const controller = new AbortController();
    let isResumingWorkspace = false;

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

        const lastWorkspaceId = getLastWorkspaceId(currentUser.id);
        const lastWorkspace = availableWorkspaces.find(
          (workspace) => workspace.id === lastWorkspaceId,
        );
        const deletionRecoveries = getPendingWorkspaceDeletions(currentUser.id);

        if (lastWorkspaceId && !lastWorkspace) {
          forgetLastWorkspace(currentUser.id);
        }

        const workspaceToResume = deletionRecoveries.length
          ? null
          : lastWorkspace ??
            (availableWorkspaces.length === 1 ? availableWorkspaces[0] : null);

        if (workspaceToResume) {
          isResumingWorkspace = true;
          rememberLastWorkspace(currentUser.id, workspaceToResume.id);
          router.replace(routes.workspace.home(workspaceToResume.id));
          return;
        }

        setUser(currentUser);
        setWorkspaces(availableWorkspaces);
        setPendingDeletions(deletionRecoveries);
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
        if (!controller.signal.aborted && !isResumingWorkspace) {
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

  async function retryWorkspaceDeletion(deletion: PendingWorkspaceDeletion) {
    if (!user) return;
    setRetryingWorkspaceId(deletion.workspaceId);
    setError(null);
    try {
      await deleteWorkspace(deletion.workspaceId, deletion.workspaceName);
      forgetPendingWorkspaceDeletion(user.id, deletion.workspaceId);
      const remainingDeletions = pendingDeletions.filter(
        (candidate) => candidate.workspaceId !== deletion.workspaceId,
      );
      const remainingWorkspaces = workspaces.filter(
        (workspace) => workspace.id !== deletion.workspaceId,
      );
      setPendingDeletions(remainingDeletions);
      setWorkspaces(remainingWorkspaces);

      if (remainingDeletions.length === 0 && remainingWorkspaces.length === 1) {
        rememberLastWorkspace(user.id, remainingWorkspaces[0].id);
        router.replace(routes.workspace.home(remainingWorkspaces[0].id));
      }
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        router.replace("/login");
        return;
      }
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "Unable to finish deleting this workspace. Please try again.",
      );
    } finally {
      setRetryingWorkspaceId(null);
    }
  }

  if (isLoading) {
    return (
      <main className="grid min-h-screen place-items-center px-6">
        <div className="text-center" role="status">
          <p className="text-xl font-semibold tracking-[-0.025em] text-foreground">
            Cortex
          </p>
          <p className="mt-2 text-sm text-muted">Opening your workspace…</p>
        </div>
      </main>
    );
  }

  return (
    <PageShell>
      <header className="flex items-center justify-between gap-4 border-b border-border/30 pb-6">
        <Link
          href="/"
          className="text-[1.35rem] font-semibold tracking-[-0.025em] text-foreground"
        >
          Cortex
        </Link>
        <Button
          type="button"
          disabled={isLoggingOut}
          onClick={logout}
          size="medium"
          variant="muted"
          className="min-h-11 disabled:cursor-wait"
        >
          {isLoggingOut ? "Logging out…" : "Log out"}
        </Button>
      </header>

      <section aria-labelledby="workspace-heading" className="py-14 sm:py-20">
        <PageHeader
          eyebrow={user?.display_name ?? user?.email ?? "Your Cortex account"}
          headingId="workspace-heading"
          title="Choose a workspace"
          description="Open a project context you own or collaborate on."
          action={
            <Link
              href={routes.newWorkspace}
              className={buttonClassName({
                size: "large",
                variant: "primary",
              })}
            >
              New workspace
            </Link>
          }
        />

          <FeedbackAlert message={error} />

          {pendingDeletions.length > 0 ? (
            <section
              aria-labelledby="deletion-recovery-heading"
              className="mt-8 overflow-hidden rounded-2xl border border-red-400/25 bg-red-500/5"
            >
              <div className="px-6 py-5">
                <h2
                  id="deletion-recovery-heading"
                  className="text-base font-semibold text-foreground"
                >
                  Finish workspace deletion
                </h2>
                <p className="mt-1 text-sm leading-6 text-muted">
                  Cortex could not finish an earlier cleanup. Retry it to remove
                  the remaining workspace data.
                </p>
              </div>
              {pendingDeletions.map((deletion) => (
                <div
                  key={deletion.workspaceId}
                  className="flex items-center justify-between gap-5 border-t border-red-400/15 px-6 py-4"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">
                      {deletion.workspaceName}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-muted">
                      This workspace remains hidden until cleanup succeeds.
                    </p>
                  </div>
                  <Button
                    type="button"
                    size="small"
                    variant="danger"
                    disabled={retryingWorkspaceId !== null}
                    onClick={() => retryWorkspaceDeletion(deletion)}
                  >
                    {retryingWorkspaceId === deletion.workspaceId
                      ? "Retrying cleanup…"
                      : "Retry cleanup"}
                  </Button>
                </div>
              ))}
            </section>
          ) : null}

          <div className="mt-10 grid gap-4 sm:grid-cols-2">
            {workspaces.map((workspace) => (
              <Link
                key={workspace.id}
                href={routes.workspace.home(workspace.id)}
                className="rounded-panel border border-border/40 bg-surface/70 p-6 transition-colors hover:border-border-strong/70 hover:bg-surface-raised"
              >
                <div className="flex items-start justify-between gap-4">
                  <h2 className="text-xl font-semibold text-foreground">
                    {workspace.name}
                  </h2>
                  <RoleBadge role={workspace.role} />
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

          {!error && workspaces.length === 0 ? (
            <p className="mt-10 rounded-panel border border-border/40 bg-surface/60 p-6 text-muted">
              You do not have access to any workspaces yet.{" "}
              <Link
                href={routes.newWorkspace}
                className="font-semibold text-accent-bright transition-colors hover:text-foreground"
              >
                Create one
              </Link>
              .
            </p>
          ) : null}
      </section>
    </PageShell>
  );
}
