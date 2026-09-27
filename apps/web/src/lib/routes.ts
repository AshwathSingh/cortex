function workspacePath(workspaceId: string) {
  return `/workspaces/${encodeURIComponent(workspaceId)}` as const;
}

export const routes = {
  account: "/account",
  workspaces: "/workspaces",
  workspace: {
    home: (workspaceId: string) => workspacePath(workspaceId),
    graph: (workspaceId: string) => `${workspacePath(workspaceId)}/graph`,
    review: (workspaceId: string) => `${workspacePath(workspaceId)}/review`,
    sources: (workspaceId: string) => `${workspacePath(workspaceId)}/sources`,
    manage: (workspaceId: string) => `${workspacePath(workspaceId)}/manage`,
  },
} as const;
