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

export type WorkspaceSource = IngestResult & {
  total_items: number;
};

/** The node labels the graph holds today. Requirement/Decision/Evidence come
 *  from the Connection Agent, which is not built, so they are not modelled. */
export type GraphNodeType = "Author" | "PullRequest" | "Issue";

export type GraphNode = {
  /** "PullRequest:42" — a GitHub id alone is not unique across labels. */
  key: string;
  id: number | string | null;
  type: GraphNodeType;
  title: string;
  url: string | null;
  state: string | null;
  repo: string | null;
  number: number | null;
};

export type GraphEdge = {
  source: string;
  target: string;
  type: string;
};

export type WorkspaceGraph = {
  workspace_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Server hit a node/edge ceiling, so the canvas is showing a subset. */
  truncated: boolean;
};
