export type AuthenticatedUser = {
  id: string;
  email: string;
  display_name: string | null;
};

export type WorkspaceRole = "OWNER" | "EDITOR" | "VIEWER";

export type WorkspaceSummary = {
  id: string;
  name: string;
  description: string | null;
  role: WorkspaceRole;
  created_at: string;
};

export type IngestResult = {
  repo: string;
  pull_requests: number;
  issues: number;
};
