function workspacePath(workspaceId: string) {
  return `/workspaces/${encodeURIComponent(workspaceId)}` as const;
}

export const routes = {
  account: "/account",
  workspaces: "/workspaces",
  newWorkspace: "/workspaces/new",
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
