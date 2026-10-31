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

/** Mirrors the `kind` values `data_sources` holds today. */
export type SourceKind = "github" | "upload";

export type WorkspaceSource = IngestResult & {
  total_items: number;
  kind: string;
  /** Sections, for an uploaded document. Zero for a repository — which counts
   *  are meaningful depends on `kind`. */
  sections: number;
  /** What to call the source on screen when its reference is not already its
   *  name. The filename for an upload, null for a repository. */
  display_name: string | null;
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
export type GraphNodeType =
  | "Author"
  | "PullRequest"
  | "Issue"
  | "Document"
  | "DocumentSection";

/** What `POST /api/workspaces/{id}/uploads` answers (US-09). */
export type UploadResult = {
  filename: string;
  /** How Cortex read the file: "pdf", "word" or "text". */
  format: string;
  sections: number;
  /** True when this filename was already here, so the reader is told their
   *  re-upload replaced it rather than added a second copy. */
  replaced: boolean;
};

export type GraphNode = {
  /** "PullRequest:42" — a GitHub id alone is not unique across labels. An
   *  uploaded document's id is a prefixed string: "DocumentSection:upload/4f1c/0". */
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
