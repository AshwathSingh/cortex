function workspacePath(workspaceId: string) {
  return `/workspaces/${encodeURIComponent(workspaceId)}` as const;
}

export const routes = {
  workspaces: "/workspaces",
  newWorkspace: "/workspaces/new",
  newWorkspaceFrom: (workspaceId: string) =>
    `/workspaces/new?from=${encodeURIComponent(workspaceId)}`,
  workspace: {
    home: (workspaceId: string) => workspacePath(workspaceId),
    account: (workspaceId: string) => `${workspacePath(workspaceId)}/account`,
    graph: (workspaceId: string) => `${workspacePath(workspaceId)}/graph`,
    review: (workspaceId: string) => `${workspacePath(workspaceId)}/review`,
    sources: (workspaceId: string) => `${workspacePath(workspaceId)}/sources`,
    ingest: (workspaceId: string) => `${workspacePath(workspaceId)}/ingest`,
    manage: (workspaceId: string) => `${workspacePath(workspaceId)}/manage`,
  },
} as const;
