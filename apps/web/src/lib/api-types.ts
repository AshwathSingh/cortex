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

/** Mirrors `app.pruning.detect.FlagRule`. */
export type FlagRule = "STALE" | "CONTRADICTED" | "THIN";

/** Mirrors `app.pruning.detect.Severity`. */
export type FlagSeverity = "HIGH" | "MEDIUM" | "LOW";

export type FlagTarget = {
  /** The canvas key, so a flag can point at the node it is about. */
  key: string;
  type: string;
  title: string;
  url: string | null;
};

/** One fact that produced a flag, so the reader can judge it (US-28 AC4). */
export type FlagEvidence = {
  label: string;
  detail: string;
};

/**
 * US-28: one finding from the Pruning Agent.
 *
 * `label` and `summary` come from the server rather than being rebuilt here:
 * the wording belongs with the rule that produced it, or the two drift.
 */
export type WorkspaceFlag = {
  id: string;
  rule: FlagRule;
  label: string;
  severity: FlagSeverity;
  summary: string;
  targets: FlagTarget[];
  evidence: FlagEvidence[];
};

export type WorkspaceFlags = {
  workspace_id: string;
  /** When the rules ran. They run on the request, so it is effectively now. */
  generated_at: string;
  flags: WorkspaceFlag[];
  /** The item ceiling was reached, so the rules saw a subset of the workspace. */
  truncated: boolean;
};
