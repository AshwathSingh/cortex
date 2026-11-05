"use client";

import { createContext, type ReactNode, useContext } from "react";

import type { AuthenticatedUser, WorkspaceSummary } from "@/lib/api-types";

export type WorkspaceContextValue = {
  workspaceId: string;
  workspace: WorkspaceSummary | null;
  user: AuthenticatedUser | null;
  isLoading: boolean;
  error: string | null;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({
  value,
  children,
}: {
  value: WorkspaceContextValue;
  children: ReactNode;
}) {
  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);

  if (!context) {
    throw new Error("useWorkspace must be used within WorkspaceProvider.");
  }

  return context;
}

/**
 * The workspace context if there is one, else null.
 *
 * For components that can use it but do not need it. The Graph Explorer only
 * wants the signed-in user's id, to decide which comments offer a delete
 * button, and refusing to render at all without a provider would make that a
 * requirement it is not.
 */
export function useOptionalWorkspace(): WorkspaceContextValue | null {
  return useContext(WorkspaceContext);
}
