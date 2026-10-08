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

/** Mirrors `app.models.data_source.SyncStatus`. */
export type SourceSyncStatus = "PENDING" | "SUCCESS" | "FAILED";

export type WorkspaceSource = IngestResult & {
  total_items: number;
  /** "github" — the only source kind that exists. */
  kind: string;
  status: SourceSyncStatus;
  /** ISO-8601. When ingestion last *started*, null for a repo ingested before
   *  sync state was recorded. */
  last_attempted_at: string | null;
  /** ISO-8601. When data last landed. Deliberately separate from the attempt:
   *  a source can be failing and still be showing three-day-old data. */
  last_synced_at: string | null;
  last_error: string | null;
  last_synced_by: string | null;
  last_synced_by_name: string | null;
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

export type GraphOrigin = {
  key: string;
  type: string;
  title: string;
  url: string;
  relationship: string | null;
  direction: "incoming" | "outgoing" | null;
};

export type GraphNodeDetails = {
  key: string;
  id: number | string | null;
  type: string;
  title: string;
  content: string | null;
  attributes: Record<string, unknown>;
  origins: GraphOrigin[];
};

export type GraphEdgeDetails = {
  key: string;
  type: string;
  title: string;
  content: string;
  source: GraphNodeDetails;
  target: GraphNodeDetails;
  attributes: Record<string, unknown>;
  origins: GraphOrigin[];
};

export type GraphSelection =
  | { kind: "node"; key: string }
  | { kind: "edge"; edge: GraphEdge }
  | null;

export type WorkspaceGraph = {
  workspace_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Server hit a node/edge ceiling, so the canvas is showing a subset. */
  truncated: boolean;
};
