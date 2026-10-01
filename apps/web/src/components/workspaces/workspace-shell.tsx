"use client";

import type { CSSProperties, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  AppSidebar,
  type SidebarLink,
} from "@/components/navigation/app-sidebar";
import {
  AppearanceIcon,
  GraphIcon,
  HomeIcon,
  ManageIcon,
  ReviewIcon,
  SourcesIcon,
} from "@/components/navigation/sidebar-icons";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { AuthenticatedUser, WorkspaceSummary } from "@/lib/api-types";
import { rememberLastWorkspace } from "@/lib/last-workspace";
import { routes } from "@/lib/routes";

import { WorkspaceProvider } from "./workspace-context";

export type SidebarAppearance = {
  width?: string;
  background?: string;
  border?: string;
  activeBackground?: string;
  hoverBackground?: string;
  accent?: string;
  activeBorder?: string;
  text?: string;
  icon?: string;
  itemRadius?: string;
  logoBackground?: string;
};

type WorkspaceShellProps = {
  workspaceId: string;
  children: ReactNode;
  reviewCount?: number;
  sidebarAppearance?: SidebarAppearance;
};

type SidebarCustomProperties = CSSProperties & {
  [key: `--cortex-sidebar-${string}`]: string | undefined;
};

function sidebarStyles(
  appearance: SidebarAppearance | undefined,
): SidebarCustomProperties {
  return {
    "--cortex-sidebar-width": appearance?.width,
    "--cortex-sidebar-background": appearance?.background,
    "--cortex-sidebar-border": appearance?.border,
    "--cortex-sidebar-active": appearance?.activeBackground,
    "--cortex-sidebar-hover": appearance?.hoverBackground,
    "--cortex-sidebar-accent": appearance?.accent,
    "--cortex-sidebar-active-border": appearance?.activeBorder,
    "--cortex-sidebar-text": appearance?.text,
    "--cortex-sidebar-icon": appearance?.icon,
    "--cortex-sidebar-item-radius": appearance?.itemRadius,
    "--cortex-sidebar-logo-background": appearance?.logoBackground,
  };
}

export function WorkspaceShell({
  workspaceId,
  children,
  reviewCount,
  sidebarAppearance,
}: WorkspaceShellProps) {
  const activePath = usePathname();
  const router = useRouter();
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null);
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadWorkspaceData() {
      setWorkspace(null);
      setError(null);
      setIsLoading(true);

      try {
        const [currentWorkspace, currentUser] = await Promise.all([
          apiRequest<WorkspaceSummary>(`/api/workspaces/${workspaceId}`, {
            signal: controller.signal,
          }),
          apiRequest<AuthenticatedUser>("/api/auth/me", {
            signal: controller.signal,
          }),
        ]);
        setWorkspace(currentWorkspace);
        setUser(currentUser);
        rememberLastWorkspace(currentUser.id, currentWorkspace.id);
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
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    }

    void loadWorkspaceData();
    return () => controller.abort();
  }, [router, workspaceId]);

  const workspaceContext = useMemo(
    () => ({ workspaceId, workspace, user, isLoading, error }),
    [error, isLoading, user, workspace, workspaceId],
  );

  const primaryLinks: SidebarLink[] = [
    {
      label: "Home",
      href: routes.workspace.home(workspaceId),
      icon: HomeIcon,
      exact: true,
    },
    {
      label: "Graph",
      href: routes.workspace.graph(workspaceId),
      icon: GraphIcon,
    },
    {
      label: "Review queue",
      href: routes.workspace.review(workspaceId),
      icon: ReviewIcon,
      badge: reviewCount,
    },
    {
      label: "Sources",
      href: routes.workspace.sources(workspaceId),
      icon: SourcesIcon,
    },
  ];

  const secondaryLinks: SidebarLink[] = [
    {
      label: "Workspace settings",
      href: routes.workspace.manage(workspaceId),
      icon: ManageIcon,
    },
  ];

  const utilityLinks = [
    {
      label: "Appearance",
      href: routes.appearance,
      icon: AppearanceIcon,
      exact: true,
    },
  ];

  return (
    <WorkspaceProvider value={workspaceContext}>
      <div
        data-workspace-id={workspaceId}
        style={sidebarStyles(sidebarAppearance)}
        className="grid min-h-screen min-w-[64rem] grid-cols-[var(--cortex-sidebar-width)_minmax(0,1fr)]"
      >
        <AppSidebar
          productLabel="Cortex"
          workspace={{
            label: workspace?.name ?? "Workspace",
            href: routes.workspaceSelector,
          }}
          account={{
            label: user?.display_name ?? user?.email ?? "Your account",
            detail: user?.display_name ? user.email : "Personal settings",
            href: routes.account,
          }}
          activePath={activePath}
          primaryLinks={primaryLinks}
          secondaryLinks={secondaryLinks}
          utilityLinks={utilityLinks}
        />
        <div className="min-w-0">
          {error ? (
            <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8">
              <FeedbackAlert message={error} />
            </main>
          ) : (
            children
          )}
        </div>
      </div>
    </WorkspaceProvider>
  );
}
