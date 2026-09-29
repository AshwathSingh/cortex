function workspacePath(workspaceId: string) {
  return `/workspaces/${encodeURIComponent(workspaceId)}` as const;
}

export const routes = {
  account: "/account",
  appearance: "/account#appearance",
  workspaces: "/workspaces",
  workspaceSelector: "/workspaces?select=1",
  workspace: {
    home: (workspaceId: string) => workspacePath(workspaceId),
    graph: (workspaceId: string) => `${workspacePath(workspaceId)}/graph`,
    review: (workspaceId: string) => `${workspacePath(workspaceId)}/review`,
    sources: (workspaceId: string) => `${workspacePath(workspaceId)}/sources`,
    manage: (workspaceId: string) => `${workspacePath(workspaceId)}/manage`,
  },
} as const;
