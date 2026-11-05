export type AuthenticatedUser = {
  id: string;
  email: string;
  display_name: string | null;
};

export type WorkspaceRole = "OWNER" | "EDITOR" | "VIEWER";

export type WorkspacePermission =
  | "sources.write"
  | "members.manage"
  | "roles.manage"
  | "workspace.update"
  | "workspace.delete";

export type WorkspaceSummary = {
  id: string;
  name: string;
  description: string | null;
  role: string;
  /** What the caller's role lets them do. Mirrors `app.permissions.Permission`.
   *  Authoritative: a custom role (US-21) has a name of its own, so `role`
   *  cannot be compared against to decide what to show. */
  permissions: WorkspacePermission[];
  created_at: string;
};

export type WorkspaceRoleDefinition = {
  id: string | null;
  name: string;
  description: string | null;
  permissions: WorkspacePermission[];
  built_in: boolean;
  member_count: number;
};

export type WorkspaceInvite = {
  id: string;
  email: string;
  role: string;
  role_id: string | null;
  expires_at: string;
  token: string;
};

export type WorkspaceInviteAcceptance = {
  workspace_id: string;
  role: string;
};

export type WorkspaceMember = {
  user_id: string;
  name: string | null;
  email: string | null;
  role: string;
  role_id: string | null;
  permissions: WorkspacePermission[];
  created_at: string;
};

export type IngestResult = {
  repo: string;
  pull_requests: number;
  issues: number;
};

/** Mirrors `app.models.data_source.SyncStatus`. */
export type SourceSyncStatus = "PENDING" | "SUCCESS" | "FAILED";

/** Mirrors the `KIND_*` constants in `app.sources.base` and the `kind` values
 *  `data_sources` holds. */
export type SourceKind = "github" | "upload" | "slack" | "discord";

/** The providers connected through an authorisation flow rather than a URL. */
export type ChatKind = "slack" | "discord";

export type WorkspaceSource = IngestResult & {
  total_items: number;
  kind: string;
  /** Sections, for an uploaded document. Which counts are meaningful depends
   *  on `kind`; the rest are zero. */
  sections: number;
  /** Channels and messages, for a chat source. */
  channels: number;
  messages: number;
  /** What to call the source on screen when its reference is not already its
   *  name: the filename for an upload, the team or server name for a chat
   *  source whose `repo` holds a Slack team id. Null for a repository. */
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
  | "DocumentSection"
  | "Channel"
  | "Message";

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

/** A chat provider this workspace has authorised (US-08). Never carries a token. */
export type ChatConnection = {
  kind: string;
  /** The Slack team id or Discord guild id. */
  external_ref: string;
  display_name: string;
  installed_by_name: string | null;
};

/** One channel offered in the picker before ingestion. */
export type ChannelOption = {
  id: string;
  name: string;
};

export type ChatIngestResult = {
  source: string;
  channels: number;
  messages: number;
};

export type GraphNode = {
  /** "PullRequest:42" — a GitHub id alone is not unique across labels. Uploaded
   *  and chat ids are prefixed strings containing slashes:
   *  "DocumentSection:upload/4f1c/0", "Message:slack/C1/1.2". */
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
