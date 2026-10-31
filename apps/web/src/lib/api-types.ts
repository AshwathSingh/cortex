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
  /** What the caller's role lets them do. Mirrors `app.permissions.Permission`.
   *  Authoritative: a custom role (US-21) has a name of its own, so `role`
   *  cannot be compared against to decide what to show. */
  permissions: string[];
  created_at: string;
};

export type IngestResult = {
  repo: string;
  pull_requests: number;
  issues: number;
};

/** Mirrors `app.models.data_source.SyncStatus`. */
export type SourceSyncStatus = "PENDING" | "SUCCESS" | "FAILED";

/** Mirrors the `KIND_*` constants in `app.sources.base`. */
export type SourceKind = "github" | "slack" | "discord";

/** The providers connected through an authorisation flow rather than a URL. */
export type ChatKind = "slack" | "discord";

export type WorkspaceSource = IngestResult & {
  total_items: number;
  kind: string;
  /** Channels and messages, for a chat source. Zero for a repository — which
   *  pair is meaningful depends on `kind`. */
  channels: number;
  messages: number;
  /** For a chat source, the team or server name: `repo` holds a Slack team id,
   *  which is not something a reader recognises. */
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
  | "Channel"
  | "Message";

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
  /** "PullRequest:42" — a GitHub id alone is not unique across labels. Chat
   *  ids are provider-prefixed and contain slashes: "Message:slack/C1/1.2". */
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
